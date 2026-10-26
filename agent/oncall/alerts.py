"""The alert state machine: pure, deterministic and testable without a database or a clock.

The rule is deliberately simple, because an alert nobody trusts is worse than no alert:

* **stale** - the newest successful (or partial) ingestion is older than the freshness threshold the
  dashboard already uses (26 h). Two consecutive checks are required so a single slow query does not
  page;
* **repeated failure** - the last two runs failed, or three of the last five did. One failed run is a
  bad night; three in five is a pattern;
* **stuck** - a `running` row older than three hours. A process that died mid-run otherwise looks like
  work in progress forever (the retained volume had exactly that row).

A firing alert keeps its `since` timestamp until it resolves, so a repeated notification can say how
long it has been firing. Recovery needs no debounce: the next clean check resolves it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

ALERT_NAME = "ingest_unhealthy"
STATE_OK = "ok"
STATE_FIRING = "firing"


@dataclass(frozen=True, slots=True)
class Observation:
    """What the evaluator is allowed to know. Built from SQL counts, never from message text."""

    now: datetime
    last_success_at: datetime | None
    recent_statuses: tuple[str, ...]
    oldest_running_at: datetime | None
    eval_last_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AlertPolicy:
    stale_minutes: int = 1560
    consecutive_failures: int = 2
    required_breaches: int = 2
    running_stale_hours: int = 3


@dataclass(frozen=True, slots=True)
class AlertState:
    name: str
    state: str
    since: datetime
    reason: str | None
    observed_minutes: float | None
    consecutive_failures: int
    breaches: int

    @property
    def firing(self) -> bool:
        return self.state == STATE_FIRING


def age_minutes(moment: datetime | None, now: datetime) -> float | None:
    if moment is None:
        return None
    reference = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    current = now if now.tzinfo else now.replace(tzinfo=UTC)
    return round((current - reference).total_seconds() / 60.0, 1)


def _leading_failures(statuses: tuple[str, ...]) -> int:
    count = 0
    for status in statuses:
        if status != "failed":
            break
        count += 1
    return count


def evaluate(
    observation: Observation,
    policy: AlertPolicy | None = None,
    previous: AlertState | None = None,
) -> tuple[AlertState, bool]:
    """Return the new state and whether it changed. `previous` carries the debounce and `since`."""
    policy = policy or AlertPolicy()
    now = observation.now
    observed = age_minutes(observation.last_success_at, now)
    failures = _leading_failures(observation.recent_statuses)
    recent = observation.recent_statuses[:5]

    reasons: list[str] = []
    immediate = False
    if observed is None:
        if observation.recent_statuses:
            reasons.append("never_succeeded")
            immediate = True
        else:
            reasons.append("no_runs")
    else:
        if failures >= policy.consecutive_failures:
            reasons.append("repeated_failure")
            immediate = True
        if len(recent) >= 3 and sum(1 for status in recent if status == "failed") >= 3:
            reasons.append("failure_pattern")
            immediate = True
        if observed > policy.stale_minutes:
            reasons.append("stale")

    if observation.oldest_running_at is not None:
        running_minutes = age_minutes(observation.oldest_running_at, now) or 0.0
        if running_minutes > policy.running_stale_hours * 60:
            reasons.append("stuck_run")
            immediate = True

    breach = bool(reasons) and reasons != ["no_runs"]
    breaches = (previous.breaches + 1 if previous else 1) if breach else 0
    firing = breach and (immediate or breaches >= policy.required_breaches)
    state = STATE_FIRING if firing else STATE_OK

    if previous is None or previous.state != state:
        since = now
    else:
        since = previous.since

    result = AlertState(
        name=ALERT_NAME,
        state=state,
        since=since,
        reason=",".join(reasons) if reasons else None,
        observed_minutes=observed,
        consecutive_failures=failures,
        breaches=breaches,
    )
    transition = previous is None or previous.state != state
    return result, transition


def message(state: AlertState, observation: Observation, *, runbook: str = "ops/runbooks/ingest-stale.md") -> str:
    """The one notification template. Counters and timestamps only - no user text, notes or prompts."""
    age = "never" if state.observed_minutes is None else f"{state.observed_minutes:.0f} min"
    last = observation.last_success_at.isoformat() if observation.last_success_at else "never"
    return (
        f"[Hermes Football] {state.name} {state.state.upper()}\n"
        f"reason: {state.reason or 'none'}\n"
        f"data age: {age}\n"
        f"last success: {last}\n"
        f"consecutive failures: {state.consecutive_failures}\n"
        f"checks in this state: {state.breaches}\n"
        f"since: {state.since.isoformat()}\n"
        f"runbook: {runbook}"
    )
