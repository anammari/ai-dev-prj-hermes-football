"""The runner's seams: the self-check, the injectable answer function, and the threshold reader.

None of these call a model. `self_check` is the important one: it is what turns "the gate passed" into
"the gate can fail", and it runs in `make test` so a scorer regression is caught before a cloud call.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent.gateway.pipeline import Answer
from db.settings import REPO_ROOT
from evals.golden import model, runner

GOLDEN = REPO_ROOT / "evals" / "golden" / "golden-2026-10-26.yaml"


def test_the_self_check_passes_on_the_real_set() -> None:
    """A synthetic perfect run passes, and all three tampers fail. If this breaks, the scoreboard is
    measuring nothing - and it is cheaper to find out here than after 48 cloud calls."""
    golden = model.load_golden(GOLDEN)
    assert runner.self_check(golden.questions) == []


def answer(**overrides) -> Answer:
    base = dict(
        text="As of 2026-10-20 12:00 UTC, source: football-data.org.",
        route="tool",
        route_source="model",
        route_confidence=0.9,
        route_reason=None,
        complexity="simple",
        grounded=True,
        data_as_of=datetime(2026, 10, 20, 12, 0, tzinfo=UTC),
        model="clef:cloud",
        latency_ms=120,
        tool_calls=[{"tool": "get_standings", "status": "ok", "latency_ms": 40}],
        turn_id=None,
        error=None,
    )
    return Answer(**{**base, **overrides})


def test_run_questions_records_what_happened_and_scores_it() -> None:
    questions = model.load_golden(GOLDEN).questions
    standings = next(question for question in questions if question.tool == "get_standings")

    def fake(question):
        # A correct answer must contain the question's required terms, so the fake echoes them: this
        # is the completeness score doing its job rather than a fixture that passes by accident.
        text = " ".join(group[0] for group in question.terms)
        return (
            answer(text=f"{text}. As of 2026-10-20 12:00 UTC, source: football-data.org."),
            {"get_standings": {"data_as_of": "2026-10-20T12:00:00Z"}},
        )

    records = runner.run_questions((standings,), fake)
    record = records[0]
    assert record["id"] == standings.id
    assert record["route"] == "tool"
    assert record["tool"] == "get_standings"
    assert record["scores"]["routing_correct"] is True
    assert record["scores"]["tool_correct"] is True
    assert record["scores"]["cited"] is True
    assert record["scores"]["fact_coverage"] == 1.0
    assert "search_knowledge" not in record["evidence"]


def test_a_failed_call_is_recorded_once_and_never_retried() -> None:
    questions = model.load_golden(GOLDEN).questions
    standings = next(question for question in questions if question.tool == "get_standings")
    calls: list[str] = []

    def fake(question):
        calls.append(question.id)
        return (
            answer(
                text="I can't check that right now.",
                route="refuse",
                grounded=False,
                tool_calls=[],
                data_as_of=None,
            ),
            {},
        )

    records = runner.run_questions((standings,), fake)
    assert calls == [standings.id], "one question, one call"
    assert records[0]["scores"]["routing_correct"] is False
    assert records[0]["scores"]["cited"] is False


def test_a_tool_failure_is_recorded_as_an_error_not_as_an_answer() -> None:
    """A contended machine must look contended, not incompetent: the pipeline answers a failed call
    with a fixed sentence and no error of its own, so the runner has to name the failure."""
    from agent.gateway.pipeline import TOOL_FAILED

    questions = model.load_golden(GOLDEN).questions
    standings = next(question for question in questions if question.tool == "get_standings")

    def fake(_question):
        return (
            answer(text=TOOL_FAILED, grounded=False, tool_calls=[], data_as_of=None),
            {},
        )

    record = runner.run_questions((standings,), fake)[0]
    assert record["error"] == "tool_unavailable"
    summary = runner.scoring.score_run((standings,), [record])
    assert summary["routing"]["errors"] == 1
    assert summary["routing"]["accuracy"] == 0.0


def test_thresholds_come_from_the_environment() -> None:
    limits = runner.thresholds_from_env({"EVAL_MIN_MACRO_F1": "0.95", "EVAL_MIN_FACT_COVERAGE": "0.8"})
    assert limits["macro_f1"] == 0.95
    assert limits["fact_coverage"] == 0.8
    assert limits["retrieval_recall"] == 0.90, "an unset floor keeps its default"


def test_the_evidence_capture_clears_between_questions() -> None:
    capture = runner.EvidenceCapture()
    capture("get_standings", {"a": 1})
    assert capture.take() == {"get_standings": {"a": 1}}
    assert capture.take() == {}
