"""One Telegram turn: route, gate, retrieve, compose, record.

The route is always one model-first decision. The complexity label then picks the execution path:

* `simple` keeps the existing one-tool, deterministic-composer path;
* `complex` lets the planner choose up to four allowlisted tools (or retrieves several notes), hands
  the collected payloads to `beam:cloud`, and verifies the citation before sending. If the composer
  fails or loses its grounding, the deterministic composer still answers.

The router never sees tool output or note text. Only the complex path, signed off on 2026-10-22, sends
those payloads to `beam:cloud`; the simple path keeps them local.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from agent.gateway import compose
from agent.gateway.answer_composer import AnswerComposer
from agent.gateway.answer_verifier import AnswerVerifier
from agent.gateway.chat import ChatError
from agent.gateway.mcp_client import MCPClient, MCPError, MCPToolError
from agent.gateway.planner import Planner
from agent.gateway.verify import verify_complex
from agent.router import Router
from agent.turn_log import TurnLog

REFUSALS = {
    "instruction_override": (
        "I can't change or reveal my instructions. "
        "I can answer football questions from the stored data and notes."
    ),
    "fabricated_fact": "I can't answer that from the data I have. I don't predict results or invent facts.",
    "unsupported_tool": "I don't have a tool for that fact yet, so I can't answer it from the data.",
    "model_refusal": "I can't help with that. I answer football questions from the stored data and notes.",
    "router_unavailable": "I can't check that right now. Please try again in a moment.",
}
CLARIFY = "Which team or competition do you mean? Name one and I'll look it up."
TOOL_FAILED = "I can't check that right now. Please try again in a moment."
COMPLEX_KNOWLEDGE_LIMIT = 8

#: Called with (tool name, payload) for every successful tool call, when a caller wants the evidence
#: as well as the answer. The eval harness is the only user: it needs to know exactly what an answer
#: was grounded on to score retrieval and faithfulness. Production passes nothing, so the callback is
#: never on the user path.
EvidenceRecorder = Callable[[str, dict], None]


@dataclass(frozen=True)
class Answer:
    text: str
    route: str
    route_source: str
    route_confidence: float | None
    route_reason: str | None
    complexity: str
    grounded: bool
    data_as_of: datetime | None
    model: str
    latency_ms: int
    tool_calls: list[dict] = field(default_factory=list)
    turn_id: str | None = None
    error: str | None = None


def _as_of(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class Pipeline:
    def __init__(
        self,
        router: Router,
        tools: MCPClient,
        turns: TurnLog,
        *,
        model: str,
        planner: Planner | None = None,
        composer: AnswerComposer | None = None,
        verifier: AnswerVerifier | None = None,
        composer_model: str = "beam:cloud",
        record_evidence: EvidenceRecorder | None = None,
    ) -> None:
        self._router = router
        self._tools = tools
        self._turns = turns
        self._model = model
        self._planner = planner
        self._composer = composer
        self._verifier = verifier
        self._composer_model = composer_model
        self._record_evidence = record_evidence

    def _evidence(self, tool: str, payload: dict) -> None:
        """Hand a successful call's payload to the recorder, if there is one.

        Deliberately not wrapped in a try: the only caller is the eval harness, which builds its own
        pipeline, and a recorder that silently dropped evidence would make a run look better than it
        was. A user answer never reaches this path with a recorder set.
        """
        if self._record_evidence is not None:
            self._record_evidence(tool, payload)

    def answer(self, message: str, *, chat_id_hash: str | None = None) -> Answer:
        started = time.perf_counter()
        decision = self._router.route(message)
        tool_calls: list[dict] = []
        data_as_of: datetime | None = None
        grounded = False
        error_text: str | None = None
        complex_path = (
            decision.complexity == "complex"
            and self._planner is not None
            and self._composer is not None
            and self._verifier is not None
        )

        if complex_path and decision.route == "tool" and decision.tool:
            text, grounded, data_as_of, tool_calls = self._complex_tools(message, decision.tool)
            model = f"{self._model}+{self._composer_model}"
        elif complex_path and decision.route == "knowledge":
            text, grounded, tool_calls = self._complex_knowledge(message)
            data_as_of = None
            model = f"{self._model}+{self._composer_model}"
        elif decision.route == "tool" and decision.tool:
            text, grounded, data_as_of, tool_calls = self._simple_tool(message, decision.tool)
            model = self._model
            error_text = None
        elif decision.route == "knowledge":
            text, grounded, tool_calls = self._simple_knowledge(message)
            data_as_of = None
            model = self._model
        elif decision.route == "clarify":
            text = CLARIFY
            model = self._model
        else:
            text = REFUSALS.get(decision.reason or "", REFUSALS["model_refusal"])
            error_text = decision.error
            model = self._model

        latency_ms = int((time.perf_counter() - started) * 1000)
        turn_id = self._turns.record(
            user_message=message,
            answer=text,
            route=decision.route,
            route_source=decision.source,
            route_confidence=decision.confidence,
            model=model,
            latency_ms=latency_ms,
            chat_id_hash=chat_id_hash,
            grounded=grounded,
            data_as_of=data_as_of,
            tool_calls=tool_calls or None,
        )
        return Answer(
            text=text,
            route=decision.route,
            route_source=decision.source,
            route_confidence=decision.confidence,
            route_reason=decision.reason,
            complexity=decision.complexity or "simple",
            grounded=grounded,
            data_as_of=data_as_of,
            model=model,
            latency_ms=latency_ms,
            tool_calls=tool_calls,
            turn_id=turn_id,
            error=error_text,
        )

    def _simple_tool(self, message: str, tool: str) -> tuple[str, bool, datetime | None, list[dict]]:
        started = time.perf_counter()
        try:
            payload = self._tools.call(tool, {"query": message})
        except (MCPToolError, MCPError):
            return TOOL_FAILED, False, None, [
                {"tool": tool, "args_summary": {"query": message}, "status": "error", "latency_ms": 0}
            ]
        self._evidence(tool, payload)
        text, grounded = compose.compose(tool, payload)
        call = {
            "tool": tool,
            "args_summary": {"query": message},
            "status": "ok",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
        return text, grounded, _as_of(payload.get("data_as_of")), [call]

    def _simple_knowledge(self, message: str) -> tuple[str, bool, list[dict]]:
        started = time.perf_counter()
        try:
            payload = self._tools.call("search_knowledge", {"query": message})
        except (MCPToolError, MCPError):
            return TOOL_FAILED, False, [
                {"tool": "search_knowledge", "args_summary": {"query": message}, "status": "error", "latency_ms": 0}
            ]
        self._evidence("search_knowledge", payload)
        text, grounded = compose.compose("search_knowledge", payload)
        call = {
            "tool": "search_knowledge",
            "args_summary": {"query": message},
            "status": "ok",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
        return text, grounded, [call]

    def _complex_tools(self, message: str, fallback_tool: str) -> tuple[str, bool, datetime | None, list[dict]]:
        assert self._planner is not None and self._composer is not None
        try:
            catalogue = self._tools.tools()
        except MCPError:
            catalogue = []
        steps = self._planner.plan(message, fallback_tool=fallback_tool, tools=catalogue)
        payloads: dict[str, dict] = {}
        calls: list[dict] = []
        for name in steps:
            started = time.perf_counter()
            try:
                payload = self._tools.call(name, {"query": message})
                payloads[name] = payload
                self._evidence(name, payload)
                calls.append(
                    {
                        "tool": name,
                        "args_summary": {"query": message},
                        "status": "ok",
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                    }
                )
            except (MCPToolError, MCPError):
                calls.append(
                    {
                        "tool": name,
                        "args_summary": {"query": message},
                        "status": "error",
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                    }
                )
        if not payloads:
            return TOOL_FAILED, False, None, calls

        stamps = [_as_of(payload.get("data_as_of")) for payload in payloads.values()]
        data_as_of = max((stamp for stamp in stamps if stamp is not None), default=None)
        text = ""
        try:
            text = self._composer.compose(message, route="database", results=payloads)
        except ChatError:
            text = ""
        if (
            text
            and verify_complex(text, route="tool", results=payloads)
            and self._verifier is not None
            and self._verifier.verify(message, route="database", results=payloads, draft=text)
        ):
            return text, True, data_as_of, calls

        fallback = "\n\n".join(compose.compose(name, payload)[0] for name, payload in payloads.items())
        fallback_grounded = any(compose.compose(name, payload)[1] for name, payload in payloads.items())
        return fallback, fallback_grounded, data_as_of, calls

    def _complex_knowledge(self, message: str) -> tuple[str, bool, list[dict]]:
        assert self._composer is not None
        started = time.perf_counter()
        try:
            payload = self._tools.call("search_knowledge", {"query": message, "k": COMPLEX_KNOWLEDGE_LIMIT})
        except (MCPToolError, MCPError):
            failed = {
                "tool": "search_knowledge",
                "args_summary": {"query": message, "k": COMPLEX_KNOWLEDGE_LIMIT},
                "status": "error",
                "latency_ms": 0,
            }
            return TOOL_FAILED, False, [failed]
        calls = [
            {
                "tool": "search_knowledge",
                "args_summary": {"query": message, "k": COMPLEX_KNOWLEDGE_LIMIT},
                "status": "ok",
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        ]
        results = {"search_knowledge": payload}
        self._evidence("search_knowledge", payload)
        text = ""
        try:
            text = self._composer.compose(message, route="notes", results=results)
        except ChatError:
            text = ""
        if (
            text
            and verify_complex(text, route="knowledge", results=results)
            and self._verifier is not None
            and self._verifier.verify(message, route="notes", results=results, draft=text)
        ):
            return text, True, calls
        fallback, grounded = compose.compose("search_knowledge", payload)
        return fallback, grounded, calls
