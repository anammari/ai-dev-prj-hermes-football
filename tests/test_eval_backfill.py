"""The M4 artifacts, imported as the scoreboard's baseline.

The import must be honest about what it is: `source: backfill`, the same sample hash the holdout ran
on, and only the metrics the M4 protocol actually measured. A backfilled run that claimed retrieval
numbers would be inventing evidence.
"""

from __future__ import annotations

from db.settings import REPO_ROOT
from evals.golden import backfill

RESULTS = REPO_ROOT / "evals" / "routing" / "results"


def test_the_v1_gate_is_imported_with_its_measured_numbers() -> None:
    run, records = backfill.from_artifact(RESULTS / "2026-10-21T21-42-43Z.json")
    assert run["source"] == "backfill"
    assert run["set_name"] == "holdout-2026-10-22"
    assert run["prompt_version"] == "1"
    assert run["metrics"]["routing"]["macro_f1"] == 0.9794745484400657
    assert run["passed"] is True
    assert run["metrics"]["gates"]["adversarial_refused"] == "8/8"
    assert len(records) == 60


def test_backfilled_runs_do_not_claim_retrieval_metrics() -> None:
    run, _records = backfill.from_artifact(RESULTS / "2026-10-22T12-19-58Z.json")
    assert "retrieval" not in run["metrics"]
    assert run["metrics"]["backfilled"] is True
    assert "not measured" in run["metrics"]["note"]


def test_the_same_artifact_always_gets_the_same_row_id() -> None:
    first = backfill.run_id_for(RESULTS / "2026-10-21T21-42-43Z.json")
    second = backfill.run_id_for(RESULTS / "2026-10-21T21-42-43Z.json")
    other = backfill.run_id_for(RESULTS / "2026-10-22T12-19-58Z.json")
    assert first == second
    assert first != other


def test_every_record_carries_its_routing_outcome() -> None:
    _run, records = backfill.from_artifact(RESULTS / "2026-10-21T21-42-43Z.json")
    misses = [record for record in records if not record["scores"]["routing_correct"]]
    assert len(misses) == 1, "the v1 gate had exactly one routing miss (results-h3)"
    assert misses[0]["id"] == "results-h3"
