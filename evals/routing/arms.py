"""The two model-first arms: identical request, different model.

Neither arm has a deterministic pre-router. Every message goes to the model, whose `surface` choice is
mapped to the contract's route and whose `tool` choice is kept when the route is `tool`. The only
difference between the arms is the model — that is what the second spike measures.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from evals.routing.ollama import OllamaError, SystemOne
from evals.routing.prompt import RouterPrompt
from evals.routing.tools import NOT_APPLICABLE

Route = Literal["tool", "knowledge", "clarify", "refuse"]
LABEL_TO_ROUTE: dict[str, Route] = {
    "database": "tool",
    "notes": "knowledge",
    "clarify": "clarify",
    "refuse": "refuse",
}


@dataclass(frozen=True)
class ModelChoice:
    route: Route | None
    tool: str | None
    confidence: float | None
    label: str | None
    error: str | None
    latency_ms: float


def route_message(model: SystemOne, prompt: RouterPrompt, message: str) -> ModelChoice:
    started = time.perf_counter()
    try:
        answers = model.ask(prompt.render(message), prompt.questions)
    except OllamaError as error:
        return ModelChoice(
            route=None,
            tool=None,
            confidence=None,
            label=None,
            error=str(error),
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    surface = answers["surface"]
    route = LABEL_TO_ROUTE.get(surface.label)
    if route is None:
        return ModelChoice(
            route=None,
            tool=None,
            confidence=surface.confidence,
            label=surface.label,
            error=f"unknown surface label {surface.label!r}",
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    tool: str | None = None
    if route == "tool":
        label = answers["tool"].label
        tool = label if label != NOT_APPLICABLE else None

    return ModelChoice(
        route=route,
        tool=tool,
        confidence=surface.confidence,
        label=surface.label,
        error=None,
        latency_ms=(time.perf_counter() - started) * 1000.0,
    )


def as_record(choice: ModelChoice) -> dict:
    return {
        "route": choice.route,
        "tool": choice.tool,
        "confidence": choice.confidence,
        "label": choice.label,
        "error": choice.error,
        "latency_ms": round(choice.latency_ms, 3),
    }
