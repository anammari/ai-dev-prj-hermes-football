"""The alert state machine, without a database or a clock.

Every case here is one the operator cares about: a stale day fires only after the debounce, a repeated
failure fires immediately, a stuck run is not mistaken for work in progress, and recovery resolves.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent.oncall.alerts import AlertPolicy, Observation, evaluate, message

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
POLICY = AlertPolicy(stale_minutes=1560, consecutive_failures=2, required_breaches=2, running_stale_hours=3)


def observation(**kwargs) -> Observation:
    defaults = dict(
        now=NOW,
        last_success_at=NOW - timedelta(minutes=30),
        recent_statuses=("succeeded",),
        oldest_running_at=None,
    )
    defaults.update(kwargs)
    return Observation(**defaults)


def test_a_fresh_ledger_is_ok() -> None:
    state, transition = evaluate(observation(), POLICY)
    assert state.state == "ok"
    assert state.reason == "no_runs" or state.reason is None
    assert transition is True


def test_staleness_needs_two_checks() -> None:
    stale = observation(last_success_at=NOW - timedelta(minutes=POLICY.stale_minutes + 60))
    first, _ = evaluate(stale, POLICY, None)
    assert first.state == "ok", "one stale check is not a page"
    assert first.breaches == 1
    second, transition = evaluate(stale, POLICY, first)
    assert second.state == "firing"
    assert transition is True
    assert second.since == NOW
    assert second.reason == "stale"


def test_the_stale_boundary_is_inclusive_of_the_threshold() -> None:
    exactly = observation(last_success_at=NOW - timedelta(minutes=POLICY.stale_minutes))
    state, _ = evaluate(exactly, POLICY)
    assert state.state == "ok"
    just_over = observation(last_success_at=NOW - timedelta(minutes=POLICY.stale_minutes + 1))
    state, _ = evaluate(just_over, POLICY)
    assert state.reason == "stale"


def test_repeated_failure_fires_immediately() -> None:
    state, _ = evaluate(observation(recent_statuses=("failed", "failed", "succeeded")), POLICY)
    assert state.state == "firing"
    assert state.reason == "repeated_failure"
    assert state.consecutive_failures == 2


def test_a_stuck_run_fires_immediately() -> None:
    state, _ = evaluate(observation(oldest_running_at=NOW - timedelta(hours=4)), POLICY)
    assert state.state == "firing"
    assert state.reason == "stuck_run"


def test_never_succeeded_fires_but_an_empty_ledger_does_not() -> None:
    never = evaluate(observation(last_success_at=None, recent_statuses=("failed",)), POLICY)[0]
    assert never.state == "firing"
    assert never.reason == "never_succeeded"
    empty = evaluate(observation(last_success_at=None, recent_statuses=()), POLICY)[0]
    assert empty.state == "ok"
    assert empty.reason == "no_runs"


def test_recovery_resolves_and_resets_the_debounce() -> None:
    stale = observation(last_success_at=NOW - timedelta(minutes=POLICY.stale_minutes + 60))
    firing, _ = evaluate(stale, POLICY, evaluate(stale, POLICY, None)[0])
    fresh = observation()
    resolved, transition = evaluate(fresh, POLICY, firing)
    assert resolved.state == "ok"
    assert resolved.breaches == 0
    assert transition is True


def test_the_since_timestamp_survives_while_firing() -> None:
    stale = observation(last_success_at=NOW - timedelta(minutes=POLICY.stale_minutes + 60))
    first, _ = evaluate(stale, POLICY, None)
    firing, _ = evaluate(stale, POLICY, first)
    later = Observation(
        now=NOW + timedelta(minutes=5),
        last_success_at=stale.last_success_at,
        recent_statuses=stale.recent_statuses,
        oldest_running_at=None,
    )
    still, transition = evaluate(later, POLICY, firing)
    assert still.state == "firing"
    assert still.since == firing.since
    assert transition is False


def test_the_notification_is_counters_and_timestamps_only() -> None:
    stale = observation(last_success_at=NOW - timedelta(minutes=POLICY.stale_minutes + 60))
    state = evaluate(stale, POLICY, evaluate(stale, POLICY, None)[0])[0]
    text = message(state, stale)
    assert "ingest_unhealthy" in text
    assert "FIRING" in text
    assert "ops/runbooks/ingest-stale.md" in text
    assert "last success" in text
    assert "user" not in text.lower()
