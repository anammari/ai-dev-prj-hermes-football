"""One Telegram turn: route, gate, call one tool, compose, record.

The order is fixed. The router sees the message and nothing else; the gate can only refuse; a tool is
called only after a `tool` decision survives the gate; the composer restates only what the tool
returned; the turn is recorded before the answer is sent. A turn that cannot be recorded is not
answered, which is what makes "every turn records its route" true rather than aspirational.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from agent.gateway import compose
from agent.gateway.mcp_client import MCPClient, MCPError, MCPToolError
from agent.router import Router
from agent.turn_log import TurnLog

REFUSALS = {
    "instruction_override": (
        "I can't change or reveal my instructions. "
        "I can answer football questions from the stored data and notes."
    ),
    "fabricated_fact": "I can't answer that from the data I have. I don't predict results or invent facts.",
    "unsupported_tool": "I don't have a tool for top-scorer totals yet, so I can't answer that from the data.",
    "model_refusal": "I can't help with that. I answer football questions from the stored data and notes.",
    "router_unavailable": "I can't check that right now. Please try again in a moment.",
}
CLARIFY = "Which team or competition do you mean? Name one and I'll look it up."
TOOL_FAILED = "I can't check that right now. Please try again in a moment."


@dataclass(frozen=True)
class Answer:
    text: str
    route: str
    route_source: str
    route_confidence: float | None
    route_reason: str | None
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
    def __init__(self, router: Router, tools: MCPClient, turns: TurnLog, *, model: str) -> None:
        self._router = router
        self._tools = tools
        self._turns = turns
        self._model = model

    def answer(self, message: str, *, chat_id_hash: str | None = None) -> Answer:
        started = time.perf_counter()
        decision = self._router.route(message)
        tool_calls: list[dict] = []
        data_as_of: datetime | None = None
        grounded = False

        if decision.route == "tool" and decision.tool:
            call_started = time.perf_counter()
            try:
                payload = self._tools.call(decision.tool, {"query": message})
                tool_calls.append(
                    {
                        "tool": decision.tool,
                        "args_summary": {"query": message},
                        "status": "ok",
                        "latency_ms": int((time.perf_counter() - call_started) * 1000),
                    }
                )
                text, grounded = compose.compose(decision.tool, payload)
                data_as_of = _as_of(payload.get("data_as_of"))
            except (MCPToolError, MCPError) as error:
                tool_calls.append(
                    {
                        "tool": decision.tool,
                        "args_summary": {"query": message},
                        "status": "error",
                        "latency_ms": int((time.perf_counter() - call_started) * 1000),
                    }
                )
                text = TOOL_FAILED
                grounded = False
                data_as_of = None
                error_text: str | None = str(error)
            else:
                error_text = None
        elif decision.route == "knowledge":
            call_started = time.perf_counter()
            try:
                payload = self._tools.call("search_knowledge", {"query": message})
                tool_calls.append(
                    {
                        "tool": "search_knowledge",
                        "args_summary": {"query": message},
                        "status": "ok",
                        "latency_ms": int((time.perf_counter() - call_started) * 1000),
                    }
                )
                text, grounded = compose.compose("search_knowledge", payload)
            except (MCPToolError, MCPError):
                tool_calls.append(
                    {
                        "tool": "search_knowledge",
                        "args_summary": {"query": message},
                        "status": "error",
                        "latency_ms": int((time.perf_counter() - call_started) * 1000),
                    }
                )
                text = TOOL_FAILED
                grounded = False
            error_text = None
        elif decision.route == "clarify":
            text = CLARIFY
            error_text = None
        else:
            text = REFUSALS.get(decision.reason or "", REFUSALS["model_refusal"])
            error_text = decision.error

        latency_ms = int((time.perf_counter() - started) * 1000)
        turn_id = self._turns.record(
            user_message=message,
            answer=text,
            route=decision.route,
            route_source=decision.source,
            route_confidence=decision.confidence,
            model=self._model,
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
            grounded=grounded,
            data_as_of=data_as_of,
            model=self._model,
            latency_ms=latency_ms,
            tool_calls=tool_calls,
            turn_id=turn_id,
            error=error_text,
        )
