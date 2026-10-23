"""The frozen holdout and its scorer: the protocol is checked, not trusted."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from evals.routing import holdout as protocol

HOLDOUT = Path(__file__).resolve().parents[1] / "evals" / "routing" / "holdout-2026-10-22.yaml"


def _record(question, *, raw_route=None, raw_tool=None, route=None, tool=None, reason=None, error=None) -> dict:
    return {
        "id": question.id,
        "class": question.class_name,
        "expected_route": question.route,
        "expected_tool": question.tool,
        "expected_reason": question.expected_reason,
        "raw_route": raw_route if raw_route is not None else question.route,
        "raw_tool": raw_tool if raw_tool is not None else question.tool,
        "route": route if route is not None else question.route,
        "tool": tool if tool is not None else question.tool,
        "reason": reason if reason is not None else question.expected_reason,
        "latency_ms": 100.0,
        "error": error,
    }


def test_the_frozen_holdout_passes_its_own_protocol() -> None:
    sample = protocol.load_holdout(HOLDOUT)
    assert len(sample.questions) == 60
    assert protocol.validate_holdout(sample) == []


def test_a_wrong_tool_fails_validation() -> None:
    sample = protocol.load_holdout(HOLDOUT)
    questions = list(sample.questions)
    index = next(i for i, question in enumerate(questions) if question.class_name == "standings")
    questions[index] = replace(questions[index], tool="get_fixtures")
    problems = protocol.validate_holdout(replace(sample, questions=tuple(questions)))
    assert any("must be tool/get_standings" in problem for problem in problems)


def test_an_unsupported_question_without_a_reason_fails_validation() -> None:
    sample = protocol.load_holdout(HOLDOUT)
    questions = list(sample.questions)
    index = next(i for i, question in enumerate(questions) if question.class_name == "unsupported")
    questions[index] = replace(questions[index], expected_reason=None)
    problems = protocol.validate_holdout(replace(sample, questions=tuple(questions)))
    assert any("expected_reason" in problem for problem in problems)


def test_a_dev_split_fails_validation() -> None:
    sample = protocol.load_holdout(HOLDOUT)
    questions = list(sample.questions)
    questions[0] = replace(questions[0], split="dev")
    problems = protocol.validate_holdout(replace(sample, questions=tuple(questions)))
    assert any("split must be holdout" in problem for problem in problems)


def test_a_perfect_gated_run_scores_one() -> None:
    sample = protocol.load_holdout(HOLDOUT)
    records = [_record(question) for question in sample.questions]
    scores = protocol.score(records, route_key="route", tool_key="tool")
    assert scores["macro_f1"] == 1.0
    assert scores["gates"]["adversarial_refused"] == "8/8"
    assert scores["gates"]["unsupported_with_reason"] == "4/4"
    assert scores["false_refusals"] == []


def test_an_errored_refusal_is_a_miss_not_a_successful_gate() -> None:
    sample = protocol.load_holdout(HOLDOUT)
    records = [_record(question) for question in sample.questions]
    index = next(i for i, question in enumerate(sample.questions) if question.class_name == "adversarial")
    records[index] = _record(sample.questions[index], route="refuse", tool=None, error="timeout")
    scores = protocol.score(records, route_key="route", tool_key="tool")
    assert scores["errors"] == 1
    assert scores["gates"]["adversarial_refused"] == "7/8"
    assert scores["accuracy"] < 1.0


def test_a_gate_refusal_of_an_answerable_question_is_counted_as_a_false_refusal() -> None:
    sample = protocol.load_holdout(HOLDOUT)
    records = [_record(question) for question in sample.questions]
    index = next(i for i, question in enumerate(sample.questions) if question.route == "tool")
    records[index] = _record(sample.questions[index], route="refuse", tool=None, reason="instruction_override")
    scores = protocol.score(records, route_key="route", tool_key="tool")
    assert sample.questions[index].id in scores["false_refusals"]
    assert scores["macro_f1"] < 1.0


def test_a_database_question_answered_from_notes_is_counted() -> None:
    sample = protocol.load_holdout(HOLDOUT)
    records = [_record(question) for question in sample.questions]
    index = next(i for i, question in enumerate(sample.questions) if question.route == "tool")
    records[index] = _record(sample.questions[index], route="knowledge", tool=None)
    scores = protocol.score(records, route_key="route", tool_key="tool")
    assert sample.questions[index].id in scores["database_to_notes"]


def test_the_markdown_says_whether_the_target_was_met() -> None:
    sample = protocol.load_holdout(HOLDOUT)
    records = [_record(question) for question in sample.questions]
    raw = protocol.score(records, route_key="raw_route", tool_key="raw_tool")
    gated = protocol.score(records, route_key="route", tool_key="tool")
    meta = {
        "run_id": "test",
        "holdout_sha256": "0" * 64,
        "prompt_version": 1,
        "model": "clef:cloud",
        "target_macro_f1": 0.90,
        "egress": "test egress",
    }
    text = protocol.render_markdown(meta, records, raw, gated)
    assert "**Target met:** yes" in text
    assert "Adversarial refused: **8/8**" in text
