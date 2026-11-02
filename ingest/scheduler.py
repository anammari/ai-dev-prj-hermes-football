"""Small daily scheduler using the configured local timezone.

The schedule is a *window*, not a nap. The first version slept for the whole interval in one
`time.sleep` and ran the job after it. That is fine on a machine that never suspends and a container
that is never recreated, and this project has neither: a laptop suspends, Docker Desktop restarts the
engine, `make obs-up` recreates the service. When the process came back at 02:48 with the day's
02:00 window already behind it, the next window was a day away, so the ledger skipped a day and the
freshness page stayed stale. The ledger showed exactly that: daily rows up to 31 October, then none.

So the loop now:

* sleeps in short slices instead of one long sleep, so a suspended host or a clock jump is noticed
  rather than slept through;
* asks the ledger whether the newest window has been served - a completed `succeeded`/`partial` run
  after that window means yes - and catches up immediately when it has not;
* retries a failed attempt after a floor, so a transient error does not spend the day and a broken
  one does not turn into a tight loop against the provider.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from datetime import time as day_time
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

#: How long one `sleep` may last. The loop re-reads the wall clock after every slice, so a host that
#: was suspended across the window runs the job on the first slice after it wakes.
CHECK_SECONDS = 60.0
#: A failed attempt is retried after this long, never in a tight loop.
RETRY_SECONDS = 900.0


def next_run(now: datetime, *, hour: int, minute: int, timezone_name: str) -> datetime:
    """The first scheduled window strictly after `now`."""
    zone = _zone(hour, minute, timezone_name)
    local_now = _aware(now).astimezone(zone)
    scheduled = datetime.combine(local_now.date(), day_time(hour, minute), tzinfo=zone)
    if scheduled <= local_now:
        scheduled += timedelta(days=1)
    return scheduled.astimezone(UTC)


def previous_run(now: datetime, *, hour: int, minute: int, timezone_name: str) -> datetime:
    """The newest scheduled window at or before `now`."""
    zone = _zone(hour, minute, timezone_name)
    local_now = _aware(now).astimezone(zone)
    scheduled = datetime.combine(local_now.date(), day_time(hour, minute), tzinfo=zone)
    if scheduled > local_now:
        scheduled = datetime.combine(
            local_now.date() - timedelta(days=1), day_time(hour, minute), tzinfo=zone
        )
    return scheduled.astimezone(UTC)


def is_due(
    now: datetime,
    last_completed: datetime | None,
    *,
    hour: int,
    minute: int,
    timezone_name: str,
) -> bool:
    """True when the newest window has passed without a completed refresh.

    "Completed" is a run that finished `succeeded` or `partial`; a `failed` run did not refresh
    anything and a `running` row has no outcome yet. No completed run at all means due.
    """
    if last_completed is None:
        return True
    return _aware(last_completed) < previous_run(now, hour=hour, minute=minute, timezone_name=timezone_name)


def next_action(
    now: datetime,
    *,
    last_completed: datetime | None,
    last_attempt: datetime | None,
    hour: int,
    minute: int,
    timezone_name: str,
    retry_seconds: float = RETRY_SECONDS,
) -> tuple[bool, datetime]:
    """Decide whether to run now, and when to look again if not.

    The second value is the moment the loop wants to be awake. `run_daily` still caps the sleep at
    `CHECK_SECONDS`; this is the target it is counting towards.
    """
    moment = _aware(now)
    if is_due(moment, last_completed, hour=hour, minute=minute, timezone_name=timezone_name):
        if last_attempt is not None and (moment - _aware(last_attempt)).total_seconds() < retry_seconds:
            return False, _aware(last_attempt) + timedelta(seconds=retry_seconds)
        return True, moment
    return False, next_run(moment, hour=hour, minute=minute, timezone_name=timezone_name)


def run_daily(
    action: Callable[[], object],
    *,
    last_completed: Callable[[], datetime | None],
    hour: int = 2,
    minute: int = 0,
    timezone_name: str = "UTC",
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    check_seconds: float = CHECK_SECONDS,
    retry_seconds: float = RETRY_SECONDS,
) -> None:
    """Run `action` once per window, catching up a window that was missed.

    `last_completed` is read from the run ledger; it is what makes a restart, a suspended host or a
    clock jump a *late* run rather than a skipped day. An action that raises is logged and retried
    after `retry_seconds`, because the ledger will not have moved forwards.
    """
    if check_seconds <= 0:
        raise ValueError("check_seconds must be positive")
    if retry_seconds < check_seconds:
        raise ValueError("retry_seconds must be at least check_seconds")
    last_attempt: datetime | None = None
    while True:
        moment = _aware(now())
        run_now, wake_at = next_action(
            moment,
            last_completed=last_completed(),
            last_attempt=last_attempt,
            hour=hour,
            minute=minute,
            timezone_name=timezone_name,
            retry_seconds=retry_seconds,
        )
        if run_now:
            last_attempt = moment
            try:
                action()
            except Exception:
                logger.exception("scheduled ingestion run failed")
            continue
        pause = max(0.0, min(check_seconds, (wake_at - _aware(now())).total_seconds()))
        sleep(pause)


def _zone(hour: int, minute: int, timezone_name: str) -> ZoneInfo:
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("schedule hour/minute is outside the clock range")
    return ZoneInfo(timezone_name)


def _aware(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes; the schedule is always UTC-aware."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
