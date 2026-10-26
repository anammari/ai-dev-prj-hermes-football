"""The named instruments, in one place so a panel and a call site cannot disagree.

Metric names are semantic and stable: a dashboard or alert written against `hermes.gateway.turns`
keeps working when the implementation changes. Attribute sets are deliberately small (route, tool,
status, complexity) to keep cardinality bounded.
"""

from __future__ import annotations

from opentelemetry import metrics
from opentelemetry.metrics import Observation

_meter = metrics.get_meter("hermes-football")

HTTP_REQUESTS = _meter.create_counter(
    "hermes.http.requests", unit="{request}", description="API requests by route template and status"
)
HTTP_DURATION = _meter.create_histogram(
    "hermes.http.duration", unit="s", description="API request duration by route template"
)
GATEWAY_TURNS = _meter.create_counter(
    "hermes.gateway.turns", unit="{turn}", description="Answered turns by route, source and complexity"
)
GATEWAY_DURATION = _meter.create_histogram(
    "hermes.gateway.duration", unit="s", description="Turn duration by route and complexity"
)
MCP_CALLS = _meter.create_counter(
    "hermes.mcp.calls", unit="{call}", description="MCP tool calls by tool and status"
)
MCP_DURATION = _meter.create_histogram(
    "hermes.mcp.duration", unit="s", description="MCP tool call duration by tool"
)
INGEST_RUNS = _meter.create_counter(
    "hermes.ingest.runs", unit="{run}", description="Ingestion runs by final status"
)
INGEST_DURATION = _meter.create_histogram(
    "hermes.ingest.duration", unit="s", description="Ingestion run duration"
)
INGEST_CALLS = _meter.create_counter(
    "hermes.ingest.upstream_calls", unit="{call}", description="Upstream calls spent by an ingestion run"
)
ONCALL_CHECKS = _meter.create_counter(
    "hermes.oncall.checks", unit="{check}", description="Alert evaluations"
)
ONCALL_DIGESTS = _meter.create_counter(
    "hermes.oncall.digests", unit="{digest}", description="Daily digests written"
)

#: Current alert state and freshness age are observable gauges: the value is read when the collector
#: asks for it, so the caller only has to keep the dict current.
_alert_state: dict[str, int] = {}
_freshness_age: dict[str, float] = {}


def _observe_alerts(options):
    return [Observation(value, {"alert": name}) for name, value in sorted(_alert_state.items())]


def _observe_freshness(options):
    return [Observation(value, {"competition": code}) for code, value in sorted(_freshness_age.items())]


ALERT_FIRING = _meter.create_observable_gauge(
    "hermes.alert.firing", callbacks=[_observe_alerts], description="1 while an alert is firing"
)
FRESHNESS_AGE = _meter.create_observable_gauge(
    "hermes.freshness.age_minutes", callbacks=[_observe_freshness], description="Age of a competition's newest data"
)


def set_alert_firing(name: str, firing: bool) -> None:
    _alert_state[name] = 1 if firing else 0


def set_freshness_age(code: str, minutes: float) -> None:
    _freshness_age[code] = round(float(minutes), 1)
