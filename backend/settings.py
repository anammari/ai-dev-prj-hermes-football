"""Backend configuration: read once, from the environment, like everything else in this repo.

`db.settings.Settings` already owns the database DSN, the agent role and the local model endpoint.
This adds only what the API itself needs, and keeps them in one object so a test can build one
without touching `os.environ`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from db.settings import REPO_ROOT, Settings

#: How old the last successful ingestion of a competition may be before `/meta/freshness` calls it
#: `stale`. The scheduled run is daily, so a day plus a couple of hours of slack is a normal state,
#: not an incident.
DEFAULT_FRESHNESS_MAX_AGE_MINUTES = 26 * 60

#: The reviewed contract. Served verbatim at `/openapi.yaml`, which is how a reviewer diffs the
#: deployed API against the repository.
DEFAULT_CONTRACT_PATH = REPO_ROOT / "openapi.yaml"


@dataclass(frozen=True, slots=True)
class BackendSettings:
    db: Settings
    agent_token: str | None = None
    freshness_max_age_minutes: int = DEFAULT_FRESHNESS_MAX_AGE_MINUTES
    contract_path: Path = DEFAULT_CONTRACT_PATH
    schedule_hour: int = 2
    schedule_minute: int = 0
    schedule_timezone: str = "UTC"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.agent_token)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> BackendSettings:
        source = os.environ if env is None else env
        return cls(
            db=Settings.from_env(env),
            # An empty or missing token is *not* an open door: `require_agent_token` fails closed and
            # the app logs a warning at startup. `.env.example` ships a placeholder so a fresh clone
            # has something to change rather than something to forget.
            agent_token=(source.get("API_AGENT_TOKEN") or "").strip() or None,
            freshness_max_age_minutes=int(
                source.get("FRESHNESS_MAX_AGE_MINUTES") or DEFAULT_FRESHNESS_MAX_AGE_MINUTES
            ),
            contract_path=Path(source.get("OPENAPI_PATH") or DEFAULT_CONTRACT_PATH),
            schedule_hour=int(source.get("INGEST_SCHEDULE_HOUR") or 2),
            schedule_minute=int(source.get("INGEST_SCHEDULE_MINUTE") or 0),
            schedule_timezone=source.get("INGEST_TIMEZONE") or "UTC",
        )
