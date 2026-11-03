"""The daily window is a schedule, not a nap: a missed window must be caught up, not skipped.

The bug this covers is in the retained ledger: daily runs up to 31 October, then none on 1 and 2
November, because the container was recreated at 02:48 with the day's window already behind it and
the old scheduler waited for the *next* one. These tests pin both halves - the window arithmetic and
the loop that reads the ledger - without a database or a real sleep.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from db.models import IngestRun
from db.session import create_db_engine, create_session_factory, session_scope
from db.settings import Settings
from ingest.pipeline import last_completed_refresh
from ingest.scheduler import (
    CHECK_SECONDS,
    is_due,
    next_action,
    next_run,
    previous_run,
    run_daily,
)


class _Stop(BaseException):
    """Escapes `run_daily`'s `except Exception`, so a test can stop the loop at a known point."""


def _sleeping(stopped: _Stop, recorded: list[float]):
    def sleep(seconds: float) -> None:
        recorded.append(seconds)
        raise stopped

    return sleep


def _never_sleep(seconds: float) -> None:
    raise AssertionError(f"run_daily slept for {seconds}s before it should have run")


def test_next_run_is_the_first_window_strictly_after_now() -> None:
    before = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)
    at_the_window = datetime(2026, 11, 2, 2, 0, tzinfo=UTC)
    after = datetime(2026, 11, 2, 2, 48, tzinfo=UTC)
    assert next_run(before, hour=2, minute=0, timezone_name="UTC") == at_the_window
    # At the exact boundary the window is already *this* one; the next is tomorrow.
    assert next_run(at_the_window, hour=2, minute=0, timezone_name="UTC") == at_the_window + timedelta(days=1)
    assert next_run(after, hour=2, minute=0, timezone_name="UTC") == at_the_window + timedelta(days=1)


def test_previous_run_is_the_newest_window_at_or_before_now() -> None:
    at_the_window = datetime(2026, 11, 2, 2, 0, tzinfo=UTC)
    assert previous_run(at_the_window, hour=2, minute=0, timezone_name="UTC") == at_the_window
    assert previous_run(at_the_window + timedelta(minutes=48), hour=2, minute=0, timezone_name="UTC") == at_the_window
    assert previous_run(at_the_window - timedelta(hours=1), hour=2, minute=0, timezone_name="UTC") == (
        at_the_window - timedelta(days=1)
    )


def test_the_window_is_read_in_the_configured_timezone() -> None:
    """02:00 in Melbourne (AEDT, UTC+11 in November) is 15:00 UTC the previous day."""
    now = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)  # 21:00 local on 1 November
    assert next_run(now, hour=2, minute=0, timezone_name="Australia/Melbourne") == datetime(
        2026, 11, 1, 15, 0, tzinfo=UTC
    )


def test_is_due_compares_the_newest_completed_refresh_with_the_newest_window() -> None:
    now = datetime(2026, 11, 2, 6, 30, tzinfo=UTC)  # the screenshot's moment
    assert is_due(now, None, hour=2, minute=0, timezone_name="UTC") is True
    assert is_due(now, datetime(2026, 10, 31, 2, 19, tzinfo=UTC), hour=2, minute=0, timezone_name="UTC") is True
    assert is_due(now, datetime(2026, 11, 2, 2, 20, tzinfo=UTC), hour=2, minute=0, timezone_name="UTC") is False


def test_next_action_runs_now_when_the_window_passed_unserved() -> None:
    now = datetime(2026, 11, 2, 2, 48, tzinfo=UTC)
    run_now, wake_at = next_action(
        now,
        last_completed=datetime(2026, 10, 31, 2, 19, tzinfo=UTC),
        last_attempt=None,
        hour=2,
        minute=0,
        timezone_name="UTC",
    )
    assert run_now is True
    assert wake_at == now


def test_next_action_waits_for_tomorrow_when_the_ledger_is_current() -> None:
    now = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)
    run_now, wake_at = next_action(
        now,
        last_completed=datetime(2026, 11, 1, 2, 20, tzinfo=UTC),
        last_attempt=None,
        hour=2,
        minute=0,
        timezone_name="UTC",
    )
    assert run_now is False
    assert wake_at == datetime(2026, 11, 2, 2, 0, tzinfo=UTC)


def test_next_action_holds_a_failed_attempt_back_for_the_retry_floor() -> None:
    now = datetime(2026, 11, 2, 2, 48, tzinfo=UTC)
    attempted = datetime(2026, 11, 2, 2, 45, tzinfo=UTC)
    run_now, wake_at = next_action(
        now,
        last_completed=datetime(2026, 10, 31, 2, 19, tzinfo=UTC),
        last_attempt=attempted,
        hour=2,
        minute=0,
        timezone_name="UTC",
        retry_seconds=900,
    )
    assert run_now is False
    assert wake_at == attempted + timedelta(seconds=900)


def test_run_daily_catches_up_a_window_missed_while_the_container_was_down() -> None:
    """The incident: the 2 November run starts on startup at 02:48, not on 3 November."""
    calls: list[str] = []

    def action() -> None:
        calls.append("run")
        raise _Stop

    with pytest.raises(_Stop):
        run_daily(
            action,
            last_completed=lambda: datetime(2026, 10, 31, 2, 19, tzinfo=UTC),
            now=lambda: datetime(2026, 11, 2, 2, 48, tzinfo=UTC),
            sleep=_never_sleep,
        )
    assert calls == ["run"]


def test_run_daily_does_not_run_when_the_ledger_is_current() -> None:
    sleeps: list[float] = []
    with pytest.raises(_Stop):
        run_daily(
            lambda: pytest.fail("the scheduler ran with a fresh ledger"),
            last_completed=lambda: datetime(2026, 11, 1, 2, 20, tzinfo=UTC),
            now=lambda: datetime(2026, 11, 2, 1, 0, tzinfo=UTC),
            sleep=_sleeping(_Stop(), sleeps),
        )
    assert sleeps == [CHECK_SECONDS]


def test_run_daily_retries_a_failed_action_after_the_floor_not_in_a_tight_loop() -> None:
    attempts: list[str] = []
    sleeps: list[float] = []

    def action() -> None:
        attempts.append("attempt")
        raise RuntimeError("upstream is down")

    with pytest.raises(_Stop):
        run_daily(
            action,
            last_completed=lambda: None,
            now=lambda: datetime(2026, 11, 2, 2, 48, tzinfo=UTC),
            sleep=_sleeping(_Stop(), sleeps),
            retry_seconds=900,
        )
    assert attempts == ["attempt"]
    assert sleeps == [CHECK_SECONDS]


def test_run_daily_refuses_a_retry_floor_below_the_poll_interval() -> None:
    with pytest.raises(ValueError):
        run_daily(lambda: None, last_completed=lambda: None, check_seconds=60, retry_seconds=10)


def test_last_completed_refresh_counts_only_runs_that_refreshed_the_competitions(migrated_url: str) -> None:
    engine = create_db_engine(replace(Settings.from_env({}), database_url=migrated_url))
    factory = create_session_factory(engine)
    completed = datetime(2026, 11, 1, 2, 19, tzinfo=UTC)
    with session_scope(factory) as session:
        session.add(
            IngestRun(
                id="refreshed",
                started_at=completed,
                finished_at=completed,
                status="partial",
                trigger="schedule",
                competitions=["PL", "BL1"],
            )
        )
        session.add(
            IngestRun(
                id="failed",
                started_at=completed + timedelta(hours=1),
                finished_at=completed + timedelta(hours=1, minutes=5),
                status="failed",
                trigger="schedule",
                competitions=["PL", "BL1"],
            )
        )
        session.add(
            IngestRun(id="running", started_at=completed + timedelta(hours=2), status="running", trigger="schedule")
        )
        # A score-delay measurement: `succeeded`, one call, no competition scope. Counting it would
        # let a single match poll serve the day's window.
        session.add(
            IngestRun(
                id="measurement",
                started_at=completed + timedelta(hours=3),
                finished_at=completed + timedelta(hours=3),
                status="succeeded",
                trigger="manual",
                competitions=None,
            )
        )
    value = last_completed_refresh(factory)
    assert value is not None
    assert value.replace(tzinfo=UTC) == completed
    engine.dispose()
