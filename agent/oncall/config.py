"""Configuration for the on-call container, read once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _flag(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class OnCallSettings:
    db_dsn: str | None = None
    stale_minutes: int = 1560
    consecutive_failures: int = 2
    required_breaches: int = 2
    running_stale_hours: int = 3
    check_seconds: int = 60
    digest_hour: int = 7
    timezone: str = "UTC"
    report_dir: Path = Path("/reports")
    eval_max_age_days: int = 8
    health_port: int = 8300
    telegram_enabled: bool = False
    telegram_token: str | None = None
    telegram_chat_id: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> OnCallSettings:
        source = os.environ if env is None else env
        return cls(
            db_dsn=(source.get("ONCALL_DB_DSN") or "").strip() or None,
            stale_minutes=int(source.get("ONCALL_STALE_MINUTES") or 1560),
            consecutive_failures=int(source.get("ONCALL_CONSECUTIVE_FAILURES") or 2),
            required_breaches=int(source.get("ONCALL_REQUIRED_BREACHES") or 2),
            running_stale_hours=int(source.get("ONCALL_RUNNING_STALE_HOURS") or 3),
            check_seconds=int(source.get("ONCALL_CHECK_SECONDS") or 60),
            digest_hour=int(source.get("ONCALL_DIGEST_HOUR") or 7),
            timezone=source.get("ONCALL_TIMEZONE") or source.get("INGEST_TIMEZONE") or "UTC",
            report_dir=Path(source.get("ONCALL_REPORT_DIR") or "/reports"),
            eval_max_age_days=int(source.get("ONCALL_EVAL_MAX_AGE_DAYS") or 8),
            health_port=int(source.get("ONCALL_PORT") or 8300),
            # Off by default. The alert bot is a separate capability with its own token and one fixed
            # template; enabling it is an owner decision (decision 0010), not a default.
            telegram_enabled=_flag(source.get("ALERT_TELEGRAM_ENABLED")),
            telegram_token=(source.get("TELEGRAM_ALERT_BOT_TOKEN") or "").strip() or None,
            telegram_chat_id=(source.get("TELEGRAM_ALERT_CHAT_ID") or "").strip() or None,
        )

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_enabled and self.telegram_token and self.telegram_chat_id)
