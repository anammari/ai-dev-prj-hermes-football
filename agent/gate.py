"""The hard safety gate around the routing model.

The model's `safety` answer is binding: any label other than `safe` becomes a refusal before a tool or
a note is touched. The gate can only downgrade, never upgrade. It also refuses a `database` choice
whose tool is `not_applicable` (a stored fact the tool surface cannot serve, such as top-scorer
totals), and it fails closed with `route_source: fallback` when the model cannot be reached.

The gate's logic is deterministic; the judgement it applies is the model's. That is the distinction
decision 0006 records: no regex, no deterministic pre-router, no message-content inspection here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Route = Literal["tool", "knowledge", "clarify", "refuse"]
RouteSource = Literal["model", "fallback"]
Safety = Literal["safe", "instruction_override", "fabricated_fact"]

SAFETY_LABELS = ("safe", "instruction_override", "fabricated_fact")
UNSUPPORTED_TOOL = "unsupported_tool"
MODEL_REFUSAL = "model_refusal"
ROUTER_UNAVAILABLE = "router_unavailable"


@dataclass(frozen=True)
class RouteDecision:
    """What one message routes to, and why. The recorder stores route/source/confidence from here."""

    route: Route
    tool: str | None
    source: RouteSource
    confidence: float | None
    reason: str | None
    surface_route: Route | None
    surface_tool: str | None
    complexity: str | None
    safety: Safety | None
    surface_confidence: float | None
    safety_confidence: float | None
    latency_ms: float
    error: str | None = None

    @property
    def refused(self) -> bool:
        return self.route == "refuse"

    def as_record(self) -> dict:
        return {
            "route": self.route,
            "tool": self.tool,
            "route_source": self.source,
            "route_confidence": self.confidence,
            "route_reason": self.reason,
            "surface_route": self.surface_route,
            "surface_tool": self.surface_tool,
            "complexity": self.complexity,
            "safety": self.safety,
            "surface_confidence": self.surface_confidence,
            "safety_confidence": self.safety_confidence,
            "latency_ms": round(self.latency_ms, 3),
            "error": self.error,
        }


def apply(
    *,
    surface_route: Route,
    tool: str | None,
    surface_confidence: float,
    complexity: str = "simple",
    safety: Safety,
    safety_confidence: float,
    latency_ms: float,
) -> RouteDecision:
    """Apply the binding gate to one successful model answer."""

    if safety in ("instruction_override", "fabricated_fact"):
        return RouteDecision(
            route="refuse",
            tool=None,
            source="model",
            confidence=safety_confidence,
            reason=safety,
            surface_route=surface_route,
            surface_tool=tool,
            complexity=complexity,
            safety=safety,
            surface_confidence=surface_confidence,
            safety_confidence=safety_confidence,
            latency_ms=latency_ms,
        )

    if surface_route == "tool" and tool is None:
        return RouteDecision(
            route="refuse",
            tool=None,
            source="model",
            confidence=surface_confidence,
            reason=UNSUPPORTED_TOOL,
            surface_route=surface_route,
            surface_tool=tool,
            complexity=complexity,
            safety=safety,
            surface_confidence=surface_confidence,
            safety_confidence=safety_confidence,
            latency_ms=latency_ms,
        )

    return RouteDecision(
        route=surface_route,
        tool=tool if surface_route == "tool" else None,
        source="model",
        confidence=surface_confidence,
        reason=MODEL_REFUSAL if surface_route == "refuse" else None,
        surface_route=surface_route,
        surface_tool=tool,
        complexity=complexity,
        safety=safety,
        surface_confidence=surface_confidence,
        safety_confidence=safety_confidence,
        latency_ms=latency_ms,
    )


def fallback(error: str, latency_ms: float) -> RouteDecision:
    """The model is unreachable or answered outside its label set: refuse, do not guess."""

    return RouteDecision(
        route="refuse",
        tool=None,
        source="fallback",
        confidence=None,
        reason=ROUTER_UNAVAILABLE,
        surface_route=None,
        surface_tool=None,
        complexity=None,
        safety=None,
        surface_confidence=None,
        safety_confidence=None,
        latency_ms=latency_ms,
        error=error,
    )
