"""The on-call agent's bounds: read-only, no message text, deterministic digest."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent.oncall import __main__ as oncall_main
from agent.oncall.alerts import AlertState, Observation
from agent.oncall.config import OnCallSettings
from agent.oncall.digest import render
from agent.oncall.queries import Snapshot
from db.settings import REPO_ROOT

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def _snapshot() -> Snapshot:
    return Snapshot(
        observation=Observation(
            now=NOW,
            last_success_at=NOW - timedelta(hours=10),
            recent_statuses=("succeeded", "partial", "failed"),
            oldest_running_at=None,
            eval_last_at=NOW - timedelta(days=1),
        ),
        freshness={
            "overall_status": "fresh",
            "max_age_minutes": 600,
            "competitions": [
                {
                    "code": "PL",
                    "status": "fresh",
                    "age_minutes": 600,
                    "last_success_at": NOW - timedelta(hours=10),
                    "rows": {"matches": 380, "standings": 20, "teams": 20},
                }
            ],
        },
        runs_24h={"succeeded": 1, "partial": 1},
        turns_24h={
            "total": 4,
            "grounded": 2,
            "grounded_rate": 0.5,
            "by_route": {"tool": 3, "refuse": 1},
            "reviewed": {"unreviewed": 4},
        },
        eval_run={"id": "run-1", "set_name": "golden", "source": "live", "passed": False, "macro_f1": 0.93},
    )


def test_settings_default_telegram_off() -> None:
    settings = OnCallSettings.from_env({})
    assert settings.telegram_enabled is False
    assert settings.telegram_ready is False
    assert settings.stale_minutes == 1560


def test_the_digest_is_deterministic_and_counts_only() -> None:
    state = AlertState(
        name="ingest_unhealthy", state="ok", since=NOW, reason=None, observed_minutes=600,
        consecutive_failures=0, breaches=0,
    )
    text = render(_snapshot(), state, generated_at=NOW, git_commit="abc123")
    assert "PL" in text
    assert "380" in text
    assert "grounded rate" not in text  # the field is `grounded: 2 (0.5)`
    assert "grounded: 2 (0.5)" in text
    assert "Message text is not read" in text
    assert "Read-only role" in text
    assert "abc123" in text


def test_the_queries_never_name_a_message_column() -> None:
    source = (REPO_ROOT / "agent" / "oncall" / "queries.py").read_text(encoding="utf-8")
    for forbidden in ("AgentTurn.user_message", "AgentTurn.answer", "select(AgentTurn.answer"):
        assert forbidden not in source, f"{forbidden} appears in the on-call queries"


def test_the_runner_writes_state_but_no_database(tmp_path: Path, monkeypatch) -> None:
    settings = OnCallSettings(db_dsn="postgresql+psycopg://readonly@example/hermes", report_dir=tmp_path)
    runner = oncall_main.Runner(settings)
    runner.engine = object()  # never used: collect is replaced below
    monkeypatch.setattr(oncall_main, "collect", lambda *args, **kwargs: _snapshot())
    runner.check(now=NOW)
    payload = json.loads((tmp_path / "alerts.json").read_text(encoding="utf-8"))
    assert payload["state"] == "ok"
    assert runner.last_check == NOW


def test_a_missing_dsn_is_reported_not_fatal(tmp_path: Path) -> None:
    runner = oncall_main.Runner(OnCallSettings(report_dir=tmp_path))
    assert runner.check(now=NOW) is None
    assert "ONCALL_DB_DSN" in (runner.last_error or "")
