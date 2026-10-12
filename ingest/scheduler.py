"""Small daily scheduler using the configured local timezone."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from datetime import time as day_time
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def next_run(now: datetime, *, hour: int, minute: int, timezone_name: str) -> datetime:
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("schedule hour/minute is outside the clock range")
    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone)
    scheduled = datetime.combine(local_now.date(), day_time(hour, minute), tzinfo=zone)
    if scheduled <= local_now:
        scheduled += timedelta(days=1)
    return scheduled.astimezone(UTC)


def run_daily(
    action: Callable[[], object],
    *,
    hour: int = 2,
    minute: int = 0,
    timezone_name: str = "UTC",
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    while True:
        scheduled = next_run(now(), hour=hour, minute=minute, timezone_name=timezone_name)
        delay = max(0.0, (scheduled - now().astimezone(UTC)).total_seconds())
        sleep(delay)
        try:
            action()
        except Exception:
            logger.exception("scheduled ingestion run failed")
