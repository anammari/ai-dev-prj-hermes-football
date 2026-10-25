"""Run the golden set through the shipped pipeline and store the result.

This is `make eval`. It is deliberately not a second agent: it builds the same runtime the Telegram
gateway builds (`agent.gateway.factory.build_runtime`), asks each golden question once, and records
what came back. A failed call is a recorded miss, never retried - the same rule the M4 holdout
followed, for the same reason: a retry hides the failure the scoreboard exists to show.

Two things are different from a conversation, on purpose:

* no turn row is written (`record_turns=False`). These are fixed questions, not users; their audit is
  `eval_results`, and flooding `agent_turns` would bury the public bot's real trail.
* the router sees only the question, as it always does; the evidence recorder captures the tool
  payloads so retrieval and citations can be scored without asking the model anything.

`--self-check` proves the scorer can fail: it scores a synthetic perfect run, then a tampered route
and a tampered fact, and exits non-zero if either tamper still passes. It needs no model and no
database, so it runs in `make test` too.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from agent.config import AgentSettings
from agent.gateway.factory import build_runtime
from agent.gateway.pipeline import TOOL_FAILED, Answer
from db.settings import REPO_ROOT
from db.settings import Settings as DbSettings
from evals.golden import metrics as scoring
from evals.golden import model as golden_model

DEFAULT_GOLDEN = REPO_ROOT / "evals" / "golden" / "golden-2026-10-26.yaml"
DEFAULT_OUT = REPO_ROOT / "evals" / "golden" / "runs"
CORPUS = REPO_ROOT / "hermes" / "agent-knowledge"


def thresholds_from_env(env: dict[str, str] | None = None) -> dict[str, float]:
    source = os.environ if env is None else env
    return {
        "macro_f1": float(source.get("EVAL_MIN_MACRO_F1") or scoring.DEFAULT_THRESHOLDS["macro_f1"]),
        "retrieval_recall": float(
            source.get("EVAL_MIN_RETRIEVAL_RECALL") or scoring.DEFAULT_THRESHOLDS["retrieval_recall"]
        ),
        "fact_coverage": float(
            source.get("EVAL_MIN_FACT_COVERAGE") or scoring.DEFAULT_THRESHOLDS["fact_coverage"]
        ),
    }


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def answer_record(question: golden_model.Question, answer: Answer, evidence: dict[str, dict]) -> dict:
    """One row: the question's labels, what the pipeline did, and the evidence it did it on."""
    tools = [str(call.get("tool")) for call in answer.tool_calls if call.get("tool")]
    return {
        "id": question.id,
        "class": question.class_name,
        "message": question.message,
        "expected_route": question.route,
        "expected_tool": question.tool,
        "route": answer.route,
        "tool": tools[0] if tools else None,
        "tools": tools,
        "reason": answer.route_reason,
        "complexity": answer.complexity,
        "grounded": answer.grounded,
        "data_as_of": answer.data_as_of.isoformat() if answer.data_as_of else None,
        "answer": answer.text,
        "latency_ms": answer.latency_ms,
        # A tool or MCP failure is not "an answer that happened to be ungrounded": it is a miss, and
        # the run's error count is the only place a contended machine becomes visible. The pipeline
        # reports it by answering with the constant refusal text and no error of its own.
        "error": answer.error or ("tool_unavailable" if answer.text == TOOL_FAILED else None),
        "evidence": evidence,
    }


def run_questions(
    questions: tuple[golden_model.Question, ...],
    answer_fn: Callable[[golden_model.Question], tuple[Answer, dict[str, dict]]],
) -> list[dict]:
    """Ask every question once, score it, and return the rows. The injectable `answer_fn` is what
    lets a test prove the scorer without a model, a stack or a network."""
    records: list[dict] = []
    for question in questions:
        answer, evidence = answer_fn(question)
        record = answer_record(question, answer, evidence)
        record["scores"] = scoring.score_question(question, record)
        records.append(record)
    return records


class EvidenceCapture:
    """Collects the payload of every tool call for the question being answered.

    The pipeline calls it once per successful call; `take()` hands the payloads to the runner and
    starts a fresh question. A call that fails records nothing, which is exactly right: a failed call
    retrieved nothing.
    """

    def __init__(self) -> None:
        self._current: dict[str, dict] = {}

    def __call__(self, tool: str, payload: dict) -> None:
        self._current[tool] = payload

    def take(self) -> dict[str, dict]:
        captured, self._current = self._current, {}
        return captured


def pipeline_answer_fn(
    runtime, capture: EvidenceCapture
) -> Callable[[golden_model.Question], tuple[Answer, dict[str, dict]]]:
    """The real thing: ask the question the way the bot would, then take the evidence it used."""
    def answer(question: golden_model.Question) -> tuple[Answer, dict[str, dict]]:
        result = runtime.pipeline.answer(question.message)
        return result, capture.take()

    return answer


# ------------------------------------------------------------------------------------------------
# Self-check: the scorer must be able to fail
# ------------------------------------------------------------------------------------------------


def synthetic_records(questions: tuple[golden_model.Question, ...]) -> list[dict]:
    """A run that should pass, built from the labels rather than from a model.

    Every answer contains all its required terms and the right citation line, and its evidence names
    the expected notes and headings. If the scorer cannot make this pass, the scorer is broken; if a
    single tampered field still passes, the gate is decoration.
    """
    records = []
    for question in questions:
        answer_text = " ".join(group[0] for group in question.terms)
        if question.route == "tool":
            answer_text += " As of 2026-10-20 12:00 UTC, source: football-data.org."
        elif question.route == "knowledge":
            answer_text += " Source: https://example.invalid/note.md (heading)."
        else:
            answer_text += " I cannot answer that from the data I have."
        evidence = (
            {
                "search_knowledge": {
                    "hits": [
                        {"source_file": note, "heading": heading, "score": 0.8}
                        for note in question.notes
                        for heading in (question.headings or ("",))
                    ]
                }
            }
            if question.notes
            else {"tool": {"data_as_of": "2026-10-20T12:00:00Z"}}
        )
        record = {
            "id": question.id,
            "class": question.class_name,
            "expected_route": question.route,
            "expected_tool": question.tool,
            "route": question.route,
            "tool": question.tool,
            "reason": question.reason,
            "answer": answer_text,
            "grounded": question.route in {"tool", "knowledge"},
            "latency_ms": 10,
            "error": None,
            "evidence": evidence,
        }
        record["scores"] = scoring.score_question(question, record)
        records.append(record)
    return records


def self_check(questions: tuple[golden_model.Question, ...]) -> list[str]:
    """Returns the problems with the scorer itself. Empty means the gate bites both ways."""
    problems: list[str] = []
    clean = synthetic_records(questions)
    passing = scoring.score_run(questions, clean)
    if scoring.failure_reasons(passing):
        problems.append(f"a synthetically perfect run does not pass: {scoring.failure_reasons(passing)}")

    by_id = {question.id: question for question in questions}

    # Route every question to the neighbouring road. One flipped record would still average above the
    # target, which is the point: a gate that only fails on a catastrophic run is a gate nobody reads.
    wrong_route = []
    for record in clean:
        tampered = dict(record)
        tampered["route"] = {"tool": "knowledge", "knowledge": "tool", "clarify": "refuse", "refuse": "clarify"}[
            record["expected_route"]
        ]
        tampered["scores"] = scoring.score_question(by_id[tampered["id"]], tampered)
        wrong_route.append(tampered)
    if not scoring.failure_reasons(scoring.score_run(questions, wrong_route)):
        problems.append("a run with every route wrong still passes the gate")

    wrong_fact = []
    for record in clean:
        tampered = dict(record)
        tampered["answer"] = "I could not find that."
        tampered["scores"] = scoring.score_question(by_id[tampered["id"]], tampered)
        wrong_fact.append(tampered)
    if not scoring.failure_reasons(scoring.score_run(questions, wrong_fact)):
        problems.append("a run with no required fact in any answer still passes the gate")

    bad_citation = []
    for record in clean:
        tampered = dict(record)
        tampered["answer"] = "Arsenal are top."
        tampered["scores"] = scoring.score_question(by_id[tampered["id"]], tampered)
        bad_citation.append(tampered)
    if not scoring.failure_reasons(scoring.score_run(questions, bad_citation)):
        problems.append("a run with no citation anywhere still passes the gate")
    return problems


# ------------------------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=None, help="ask only the first N questions")
    parser.add_argument("--only-class", default=None, help="ask only one class (a smoke run)")
    parser.add_argument("--no-store", action="store_true", help="score and print, write nothing")
    parser.add_argument("--self-check", action="store_true", help="prove the scorer can fail, then exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    golden = golden_model.load_golden(args.golden)
    problems = golden_model.validate_golden(golden)
    if problems:
        print("golden set failed its own labels:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    if args.self_check:
        found = self_check(golden.questions)
        for problem in found:
            print(f"self-check: {problem}", file=sys.stderr)
        print("self-check: ok" if not found else "self-check: FAILED")
        return 0 if not found else 3

    questions = golden.questions
    if args.only_class:
        questions = tuple(question for question in questions if question.class_name == args.only_class)
    if args.limit is not None:
        questions = questions[: args.limit]

    settings = AgentSettings.from_env()
    capture = EvidenceCapture()
    runtime = build_runtime(settings, record_turns=False, record_evidence=capture)
    started = datetime.now(UTC)
    try:
        records = run_questions(questions, pipeline_answer_fn(runtime, capture))
    finally:
        runtime.close()
    finished = datetime.now(UTC)

    metrics = scoring.score_run(questions, records)
    limits = thresholds_from_env()
    failures = scoring.failure_reasons(metrics, limits)

    run = {
        "run_id": str(uuid.uuid4()),
        "set_name": args.golden.stem,
        "golden_set_sha256": _sha256(args.golden),
        "prompt_version": str(getattr(runtime.router, "prompt_version", "") or "unknown"),
        "model": settings.router_model,
        "git_commit": _git_commit(),
        "source": "live",
        "status": "succeeded",
        "passed": not failures,
        "metrics": {**metrics, "runtime": {"composer": settings.composer_model, "thresholds": limits}},
        "failure_reasons": failures,
        "started_at": started,
        "finished_at": finished,
    }

    artifact = args.out_dir / f"{run['run_id']}.json"
    if not args.no_store:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        artifact.write_text(
            json.dumps({"run": {**run, "started_at": started.isoformat(), "finished_at": finished.isoformat()},
                        "records": records}, indent=2) + "\n",
            encoding="utf-8",
        )
        from evals.golden import store

        # The store writes with the owner URL (like a migration); `AgentSettings` is the model
        # configuration, not a database URL, so the store gets its own settings object.
        store.store_run(DbSettings.from_env(), run, records)

    routing = metrics["routing"]
    retrieval = metrics["retrieval"]
    answers = metrics["answers"]
    print(f"run {run['run_id']} · set {run['set_name']} · prompt v{run['prompt_version']} · model {run['model']}")
    print(f"  routing   macro-F1 {routing['macro_f1']:.3f} · accuracy {routing['accuracy']:.3f} "
          f"· errors {routing['errors']} · p95 {routing['latency_p95_ms']:.0f} ms")
    print(f"  retrieval recall@k {retrieval['recall_at_k']} · headings {retrieval['heading_recall']}")
    print(f"  answers   fact coverage {answers['fact_coverage']} · citations {answers['citation_coverage']:.2f}")
    print(f"  gates     {metrics['gates']}")
    print(f"  passed    {'yes' if run['passed'] else 'no'}")
    for reason in failures:
        print(f"  failed    {reason}")
    if not args.no_store:
        print(f"  wrote     {artifact.relative_to(REPO_ROOT)} and one eval_runs row")
    return 0 if run["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
