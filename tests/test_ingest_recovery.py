"""A killed run must not look alive forever."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from db.models import IngestRun
from db.session import create_db_engine, create_session_factory, session_scope
from db.settings import Settings
from ingest.pipeline import close_orphaned_runs


def test_an_old_running_row_is_closed_and_a_fresh_one_is_left_alone(migrated_url: str) -> None:
    engine = create_db_engine(replace(Settings.from_env({}), database_url=migrated_url))
    factory = create_session_factory(engine)
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    with session_scope(factory) as session:
        session.add(
            IngestRun(id="old-run", started_at=now - timedelta(hours=5), status="running", trigger="schedule")
        )
        session.add(
            IngestRun(id="fresh-run", started_at=now - timedelta(minutes=10), status="running", trigger="schedule")
        )
    closed = close_orphaned_runs(factory, now=now, max_age_hours=3)
    assert closed == ["old-run"]
    with session_scope(factory) as session:
        old = session.get(IngestRun, "old-run")
        fresh = session.get(IngestRun, "fresh-run")
        assert old.status == "failed"
        assert old.finished_at is not None
        assert any(error["resource"] == "recovery" for error in old.errors or [])
        assert fresh.status == "running"
    engine.dispose()
