"""Import the two M4 holdout runs so the scoreboard has a baseline on day one.

The routing gate was measured before this table existed. Re-running it would answer a different
question (the code has moved) and would spend cloud calls to reproduce a number we already have, so
the committed artifacts are imported instead - marked `source: backfill` so nobody mistakes them for a
live run.

The import is idempotent: the row id is derived from the artifact's own run id, so running this twice
leaves one row per artifact. The per-question results are imported with the same route/tool columns
the live runner writes; their `scores` carry only what the artifact recorded (routing correctness and
the gates), because the artifact never stored passages or answers.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from db.settings import REPO_ROOT, Settings
from evals.golden import store

#: The artifacts worth importing: the independent v1 gate and the v2 regression. The archived M3b
#: two-model comparison is a different protocol and is deliberately not imported.
ARTIFACTS = (
    "2026-10-21T21-42-43Z.json",
    "2026-10-22T12-19-58Z.json",
)
RESULTS = REPO_ROOT / "evals" / "routing" / "results"


def run_id_for(artifact: Path) -> str:
    """A stable uuid from the artifact's own run id, so a second import is the same row."""
    digest = hashlib.sha256(f"backfill:{artifact.name}".encode()).hexdigest()
    return str(uuid.UUID(digest[:32]))


def from_artifact(artifact: Path) -> tuple[dict, list[dict]]:
    body = json.loads(artifact.read_text(encoding="utf-8"))
    meta = body["meta"]
    gated = body["gated"]
    run = {
        "run_id": run_id_for(artifact),
        "set_name": "holdout-2026-10-22",
        "golden_set_sha256": meta["holdout_sha256"],
        "prompt_version": str(meta["prompt_version"]),
        "model": meta["model"],
        "git_commit": meta.get("git_commit", "unavailable"),
        "source": "backfill",
        "status": "succeeded",
        "passed": gated["macro_f1"] >= meta["target_macro_f1"],
        "metrics": {
            "routing": {
                "n": gated["n"],
                "accuracy": gated["accuracy"],
                "macro_precision": gated["macro_precision"],
                "macro_recall": gated["macro_recall"],
                "macro_f1": gated["macro_f1"],
                "per_route": gated["per_route"],
                "tool": gated["tool"],
                "errors": gated["errors"],
            },
            "gates": gated["gates"],
            "backfilled": True,
            "note": (
                "imported from evals/routing/results; routing only. Retrieval, citations and fact "
                "coverage were not measured by the M4 protocol, so they are absent rather than zero."
            ),
        },
        "failure_reasons": (
            [] if gated["macro_f1"] >= meta["target_macro_f1"] else ["gated macro-F1 below the 0.90 target"]
        ),
        "started_at": meta["created_at"],
        "finished_at": meta["created_at"],
    }
    records = [
        {
            "id": record["id"],
            "class": record["class"],
            "expected_route": record["expected_route"],
            "expected_tool": record.get("expected_tool"),
            "route": record["route"],
            "tool": record.get("tool"),
            "latency_ms": record.get("latency_ms"),
            "error": record.get("error"),
            "scores": {
                "routing_correct": record["route"] == record["expected_route"],
                **(
                    {"tool_correct": record.get("tool") == record["expected_tool"]}
                    if record.get("expected_tool")
                    else {}
                ),
            },
        }
        for record in body["records"]
    ]
    return run, records


def main(settings: Settings | None = None) -> int:
    configured = settings or Settings.from_env()
    for name in ARTIFACTS:
        artifact = RESULTS / name
        if not artifact.exists():
            print(f"missing artifact: {artifact}")
            return 2
        run, records = from_artifact(artifact)
        try:
            store.store_run(configured, run, records)
            print(f"imported {name} as {run['run_id']} ({run['metrics']['routing']['macro_f1']:.3f} macro-F1)")
        except ValueError:
            print(f"already imported: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
