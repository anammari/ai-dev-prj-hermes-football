"""The scoreboard writer: one row per run, one row per question, and no silent duplicate.

`store_run` is the only writer of `eval_runs`/`eval_results`, and it uses the owner URL - the same
split migrations and ingestion use. These tests run it against the migrated SQLite file the rest of
the unit suite uses, so the foreign key and the JSON columns are the real ones.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from db.models import EvalResult, EvalRun
from evals.golden import store


def a_run(**overrides) -> dict:
    base = dict(
        run_id="11111111-2222-3333-4444-555555555555",
        set_name="golden-test",
        golden_set_sha256="a" * 64,
        prompt_version="2",
        model="clef:cloud",
        git_commit="4f3bde9",
        source="live",
        status="succeeded",
        passed=True,
        metrics={"routing": {"macro_f1": 0.97}},
        failure_reasons=[],
        started_at=datetime(2026, 10, 25, 10, 0, tzinfo=UTC),
        finished_at=datetime(2026, 10, 25, 10, 4, tzinfo=UTC),
    )
    return {**base, **overrides}


def a_record(**overrides) -> dict:
    base = dict(
        id="g-tool-standings-1",
        **{"class": "standings"},
        expected_route="tool",
        expected_tool="get_standings",
        route="tool",
        tool="get_standings",
        latency_ms=800,
        error=None,
        scores={"routing_correct": True, "tool_correct": True, "fact_coverage": 1.0},
        evidence={"get_standings": {"data_as_of": "2026-10-20T12:00:00Z"}},
    )
    return {**base, **overrides}


def test_a_run_and_its_results_are_stored_once(settings, migrated_url, session) -> None:
    store.store_run(settings, a_run(), [a_record(), a_record(id="g-knowledge-1", **{"class": "formats"})])
    session.expire_all()
    run = session.get(EvalRun, "11111111-2222-3333-4444-555555555555")
    assert run is not None
    assert run.set_name == "golden-test"
    assert run.metrics["routing"]["macro_f1"] == 0.97
    assert session.scalar(select(func.count()).select_from(EvalResult)) == 2


def test_the_store_refuses_a_replayed_run_id(settings, migrated_url, session) -> None:
    """Two rows with the same id would count a run twice on the scoreboard."""
    store.store_run(settings, a_run(), [a_record()])
    with pytest.raises(ValueError):
        store.store_run(settings, a_run(), [a_record()])
    assert session.scalar(select(func.count()).select_from(EvalRun)) == 1


def test_the_evidence_is_stored_as_passages_not_as_a_copy_of_the_database(settings, migrated_url, session) -> None:
    knowledge = a_record(
        id="g-knowledge-1",
        **{"class": "formats"},
        expected_route="knowledge",
        expected_tool=None,
        route="knowledge",
        tool=None,
        evidence={
            "search_knowledge": {
                "hits": [
                    {"source_file": "formats/championship-playoffs.md", "heading": "How it works", "score": 0.8}
                ]
            }
        },
    )
    store.store_run(settings, a_run(), [knowledge])
    stored = session.scalar(select(EvalResult).where(EvalResult.question_id == "g-knowledge-1"))
    assert stored is not None
    assert stored.retrieved == [
        {"source_file": "formats/championship-playoffs.md", "heading": "How it works", "score": 0.8}
    ]
    assert "chunk_text" not in str(stored.retrieved), "the passage is a reference, not a copy of the note"
