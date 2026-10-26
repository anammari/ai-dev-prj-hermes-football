"""Read-only queries for the on-call agent.

Every query names the columns it reads. `user_message` and `answer` are never selected, not even to
count them; `tests/test_oncall.py` parses this module and fails if either name appears in a select.
The connection is the `agent_readonly` role, so a mistake here is refused by Postgres as well.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from agent.oncall.alerts import Observation
from backend.services.freshness import REFRESHED, freshness_report
from backend.settings import BackendSettings
from db.models import AgentTurn, EvalRun, IngestRun
from db.session import create_db_engine
from db.settings import Settings


@dataclass(slots=True)
class Snapshot:
    observation: Observation
    freshness: dict[str, Any] = field(default_factory=dict)
    runs_24h: dict[str, int] = field(default_factory=dict)
    turns_24h: dict[str, Any] = field(default_factory=dict)
    eval_run: dict[str, Any] | None = None

    @property
    def eval_age_days(self) -> float | None:
        moment = self.observation.eval_last_at
        if moment is None:
            return None
        reference = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
        return round((self.observation.now - reference).total_seconds() / 86400.0, 1)


def engine_for(dsn: str) -> Engine:
    return create_db_engine(Settings(database_url=dsn))


def collect(engine: Engine, *, now: datetime | None = None, stale_minutes: int = 1560) -> Snapshot:
    moment = now or datetime.now(UTC)
    since = moment - timedelta(hours=24)
    settings = BackendSettings(
        db=Settings(database_url=engine.url.render_as_string(hide_password=False)),
        freshness_max_age_minutes=stale_minutes,
    )
    with Session(engine) as session:
        statuses = tuple(
            session.scalars(
                select(IngestRun.status).order_by(IngestRun.started_at.desc()).limit(5)
            )
        )
        last_success = session.scalar(
            select(func.max(IngestRun.finished_at)).where(
                IngestRun.status.in_(REFRESHED),
                IngestRun.finished_at.is_not(None),
                IngestRun.finished_at <= moment,
            )
        )
        oldest_running = session.scalar(
            select(func.min(IngestRun.started_at)).where(IngestRun.status == "running")
        )
        eval_last = session.scalar(select(func.max(EvalRun.started_at)))
        eval_row = session.scalars(select(EvalRun).order_by(EvalRun.started_at.desc()).limit(1)).first()

        report = freshness_report(session, settings, now=moment)
        runs_24h = dict(
            session.execute(
                select(IngestRun.status, func.count())
                .where(IngestRun.started_at >= since)
                .group_by(IngestRun.status)
            ).all()
        )
        turns_total = int(
            session.scalar(select(func.count()).select_from(AgentTurn).where(AgentTurn.created_at >= since)) or 0
        )
        grounded = int(
            session.scalar(
                select(func.count())
                .select_from(AgentTurn)
                .where(AgentTurn.created_at >= since, AgentTurn.grounded.is_(True))
            )
            or 0
        )
        by_route = dict(
            session.execute(
                select(AgentTurn.route, func.count())
                .where(AgentTurn.created_at >= since)
                .group_by(AgentTurn.route)
            ).all()
        )
        reviewed = dict(
            session.execute(
                select(AgentTurn.review_status, func.count())
                .where(AgentTurn.created_at >= since)
                .group_by(AgentTurn.review_status)
            ).all()
        )

    observation = Observation(
        now=moment,
        last_success_at=_aware(last_success),
        recent_statuses=tuple(str(status) for status in statuses),
        oldest_running_at=_aware(oldest_running),
        eval_last_at=_aware(eval_last),
    )
    return Snapshot(
        observation=observation,
        freshness=report,
        runs_24h={str(key): int(value) for key, value in runs_24h.items()},
        turns_24h={
            "total": turns_total,
            "grounded": grounded,
            "grounded_rate": round(grounded / turns_total, 3) if turns_total else None,
            "by_route": {str(key): int(value) for key, value in by_route.items()},
            "reviewed": {str(key): int(value) for key, value in reviewed.items()},
        },
        eval_run=_eval_row(eval_row),
    )


def _eval_row(row: EvalRun | None) -> dict[str, Any] | None:
    if row is None:
        return None
    metrics = row.metrics or {}
    routing = metrics.get("routing") or {}
    return {
        "id": row.id,
        "set_name": row.set_name,
        "source": row.source,
        "passed": bool(row.passed),
        "macro_f1": routing.get("macro_f1"),
        "started_at": _aware(row.started_at).isoformat() if row.started_at else None,
    }


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
