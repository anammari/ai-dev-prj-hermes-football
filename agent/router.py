"""The production router: one model call, then the hard gate.

The router sees the user message and the fixed label sets in `prompts/0003-agent-router.md`. It never
sees retrieved text, tool output, the hand label or the conversation. `route()` returns a decision the
gateway can record: route, source, confidence and the reason a refusal happened.
"""

from __future__ import annotations

import time
from pathlib import Path

from agent import gate
from agent.client import DecisionClient, DecisionError
from agent.prompt import RouterPrompt, load_router_prompt
from db.settings import REPO_ROOT

LABEL_TO_ROUTE = {
    "database": "tool",
    "notes": "knowledge",
    "clarify": "clarify",
    "refuse": "refuse",
}
NOT_APPLICABLE = "not_applicable"


class Router:
    def __init__(self, client: DecisionClient, prompt: RouterPrompt) -> None:
        self._client = client
        self._prompt = prompt

    @property
    def prompt_version(self) -> int:
        return self._prompt.version

    def route(self, message: str) -> gate.RouteDecision:
        started = time.perf_counter()
        try:
            answers = self._client.ask(self._prompt.render(message), self._prompt.questions)
        except DecisionError as error:
            return gate.fallback(str(error), (time.perf_counter() - started) * 1000.0)

        latency_ms = (time.perf_counter() - started) * 1000.0
        surface = answers.get("surface")
        safety = answers.get("safety")
        tool_answer = answers.get("tool")
        complexity = answers.get("complexity")
        if surface is None or safety is None or tool_answer is None or complexity is None:
            return gate.fallback("decision response is missing a question", latency_ms)

        surface_route = LABEL_TO_ROUTE.get(surface.label)
        if surface_route is None:
            return gate.fallback(f"unknown surface label {surface.label!r}", latency_ms)
        if safety.label not in gate.SAFETY_LABELS:
            return gate.fallback(f"unknown safety label {safety.label!r}", latency_ms)
        if complexity.label not in ("simple", "complex"):
            return gate.fallback(f"unknown complexity label {complexity.label!r}", latency_ms)

        tool: str | None = None
        if surface_route == "tool":
            if tool_answer.label not in (NOT_APPLICABLE, *TOOL_NAMES):
                return gate.fallback(f"unknown tool label {tool_answer.label!r}", latency_ms)
            tool = None if tool_answer.label == NOT_APPLICABLE else tool_answer.label

        return gate.apply(
            surface_route=surface_route,
            tool=tool,
            surface_confidence=surface.confidence,
            complexity=complexity.label,
            safety=safety.label,  # type: ignore[arg-type]
            safety_confidence=safety.confidence,
            latency_ms=latency_ms,
        )


#: The tool labels the router may name. Kept here rather than imported from the MCP server so the
#: router package has no dependency on the tool implementation.
TOOL_NAMES = (
    "get_standings",
    "get_fixtures",
    "get_match_result",
    "get_team_form",
    "get_head_to_head",
    "get_data_freshness",
    "get_top_scorers",
)

DEFAULT_PROMPT = REPO_ROOT / "prompts" / "0003-agent-router.md"


def build_router(
    *,
    base_url: str,
    model: str,
    prompt_path: Path = DEFAULT_PROMPT,
    timeout: float = 20.0,
) -> Router:
    prompt = load_router_prompt(prompt_path)
    return Router(DecisionClient(base_url=base_url, model=model, timeout=timeout), prompt)
