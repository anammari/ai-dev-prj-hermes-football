"""The scorer, against made-up records: every number it reports has to be reproducible by hand.

These tests do not call a model, the stack or the golden runner. They pin the arithmetic and, more
importantly, the failure modes: a failed call is a miss (not a correct refusal), a complex answer that
used the expected tool second still counts, and a gate that cannot fail would be caught by
`test_the_gate_bites_on_every_dimension`.
"""

from __future__ import annotations

from evals.golden import metrics
from evals.golden.model import Question


def question(**overrides) -> Question:
    base = dict(
        id="q-1",
        class_name="formats",
        message="how does the playoff work",
        route="knowledge",
        tool=None,
        notes=("formats/championship-playoffs.md",),
        headings=("How the Championship promotion play-offs work",),
        facts=(),
        terms=(("play-off", "playoff"), ("two legs", "two-legged")),
        reason=None,
        rationale="a written format, not a table row",
    )
    return Question(**{**base, **overrides})


def record(**overrides) -> dict:
    base = dict(
        id="q-1",
        **{"class": "formats"},
        expected_route="knowledge",
        expected_tool=None,
        route="knowledge",
        tool=None,
        answer="The play-off is decided over two legs. Source: https://example.invalid/a.md (heading).",
        grounded=True,
        latency_ms=12,
        error=None,
        evidence={
            "search_knowledge": {
                "hits": [
                    {
                        "source_file": "formats/championship-playoffs.md",
                        "heading": "How the Championship promotion play-offs work",
                        "score": 0.81,
                    }
                ]
            }
        },
    )
    return {**base, **overrides}


# ------------------------------------------------------------------------------------------------
# Term coverage
# ------------------------------------------------------------------------------------------------


def test_term_coverage_matches_whole_words_and_alternatives() -> None:
    assert metrics.term_coverage("a two-legged play-off", (("two legs", "two-legged"),)) == 1.0
    assert metrics.term_coverage("the playoff is decided over two legs", (("play-off", "playoff"),)) == 1.0
    # Whole words only: "playoffs" is not "playoff". The golden set writes the alternative spellings
    # in one group, which is why the terms are groups and not strings.
    assert metrics.term_coverage("the playoffs", (("play-off", "playoff"),)) == 0.0
    assert metrics.term_coverage("the playoffs", (("two legs",),)) == 0.0
    assert metrics.term_coverage("", (("two legs",),)) == 0.0
    assert metrics.term_coverage("anything", ()) is None


def test_term_coverage_does_not_match_inside_another_word() -> None:
    """`gd` must not match `gdpr`, or every answer would cover a goal-difference term by accident."""
    assert metrics.term_coverage("the gdpr rules", (("gd",),)) == 0.0


# ------------------------------------------------------------------------------------------------
# Retrieval and citations
# ------------------------------------------------------------------------------------------------


def test_note_recall_counts_a_note_once_and_says_nothing_when_no_note_is_expected() -> None:
    two = question(notes=("formats/championship-playoffs.md", "b.md"))
    assert metrics.note_recall(two, record()["evidence"]) == 0.5
    assert metrics.note_recall(question(notes=()), record()["evidence"]) is None


def test_note_recall_is_zero_when_the_call_failed() -> None:
    """A failed retrieval found nothing. Returning `None` would quietly drop the question from the
    average, which is how a bad run looks good."""
    assert metrics.note_recall(question(), {}) == 0.0


def test_heading_recall_follows_the_retrieved_heading() -> None:
    assert metrics.heading_recall(question(), record()["evidence"]) == 1.0
    wrong = question(headings=("A heading nobody retrieved",))
    assert metrics.heading_recall(wrong, record()["evidence"]) == 0.0


def test_citations_are_the_composer_s_own_lines() -> None:
    assert metrics.cited(question(), "text. Source: https://x/y.md (heading).") is True
    assert metrics.cited(question(), "text with no source.") is False
    tool_q = question(route="tool", tool="get_standings", notes=(), headings=(), terms=())
    assert metrics.cited(tool_q, "Arsenal are 1st. As of 2026-10-20 12:00 UTC, source: football-data.org.") is True
    assert metrics.cited(tool_q, "Arsenal are 1st.") is False
    clarify = question(route="clarify", tool=None, notes=(), headings=(), terms=())
    assert metrics.cited(clarify, "Which team do you mean?") is True


# ------------------------------------------------------------------------------------------------
# The run summary
# ------------------------------------------------------------------------------------------------


def perfect_run() -> tuple[tuple[Question, ...], list[dict]]:
    questions = tuple(
        question(id=f"q-{route}", class_name=cls, route=route, tool=tool, notes=(), headings=(), terms=())
        for route, cls, tool in (
            ("tool", "standings", "get_standings"),
            ("knowledge", "formats", None),
            ("clarify", "clarify", None),
            ("refuse", "fabricated", None),
        )
    )
    records = [
        record(
            id=f"q-{route}",
            **{"class": cls},
            expected_route=route,
            expected_tool=tool,
            route=route,
            tool=tool,
            answer=(
                "As of 2026-10-20 12:00 UTC, source: football-data.org."
                if route == "tool"
                else "Source: https://x/y.md (heading)."
                if route == "knowledge"
                else "I cannot answer that."
            ),
            grounded=route in {"tool", "knowledge"},
            evidence={},
        )
        for route, cls, tool in (
            ("tool", "standings", "get_standings"),
            ("knowledge", "formats", None),
            ("clarify", "clarify", None),
            ("refuse", "fabricated", None),
        )
    ]
    for item in records:
        item["scores"] = metrics.score_question(next(q for q in questions if q.id == item["id"]), item)
    return questions, records


def test_a_perfect_run_scores_one_everywhere_and_passes() -> None:
    questions, records = perfect_run()
    summary = metrics.score_run(questions, records)
    assert summary["routing"]["macro_f1"] == 1.0
    assert summary["routing"]["accuracy"] == 1.0
    assert summary["answers"]["citation_coverage"] == 1.0
    assert summary["gates"]["false_refusals"] == []
    assert metrics.failure_reasons(summary) == []


def test_macro_averages_only_the_routes_the_run_exercised() -> None:
    """A smoke run with one route must not be averaged against three empty routes: 0.25 for a perfect
    answer is a number nobody should see, and the full run is unaffected because all four have
    support there."""
    questions, records = perfect_run()
    summary = metrics.score_run(questions[:1], records[:1])
    assert summary["routing"]["macro_f1"] == 1.0
    assert summary["routing"]["routes_with_support"] == ["tool"]
    full = metrics.score_run(questions, records)
    assert full["routing"]["routes_with_support"] == ["tool", "knowledge", "clarify", "refuse"]
    assert full["routing"]["macro_f1"] == 1.0


def test_a_smoke_run_does_not_get_a_gate_verdict() -> None:
    questions, records = perfect_run()
    summary = metrics.score_run(questions[:1], [dict(records[0], route="knowledge", tool=None)])
    assert metrics.failure_reasons(summary) != []
    assert metrics.failure_reasons(summary, full=False) == []


def test_the_gate_bites_on_every_dimension() -> None:
    """Each dimension gets its own tamper, because a gate that only catches one of them is a gate
    nobody can trust."""
    questions, records = perfect_run()

    def tampered(**changes) -> dict:
        copy = [dict(item) for item in records]
        copy[0] = {**copy[0], **changes}
        copy[0]["scores"] = metrics.score_question(questions[0], copy[0])
        return metrics.score_run(questions, copy)

    assert metrics.failure_reasons(tampered(route="knowledge", tool=None)), "a wrong route must fail"
    assert metrics.failure_reasons(tampered(answer="Arsenal are 1st.")), "a missing citation must fail"
    assert metrics.failure_reasons(tampered(error="tool timeout", route=None)), "a failed call must fail"

    refused = [dict(item) for item in records]
    refused[0] = {**refused[0], "route": "refuse", "route_reason": "model_refusal"}
    refused[0]["scores"] = metrics.score_question(questions[0], refused[0])
    assert metrics.failure_reasons(metrics.score_run(questions, refused)), "a false refusal must fail"


def test_an_errored_call_is_a_miss_not_a_correct_refusal() -> None:
    """The M4 rule, inherited: a failed call has no route, so it cannot count as a correct refusal."""
    questions = (question(route="refuse", class_name="adversarial", notes=(), headings=(), terms=()),)
    failed = record(
        id="q-1",
        **{"class": "adversarial"},
        expected_route="refuse",
        route=None,
        error="model unreachable",
    )
    failed["scores"] = metrics.score_question(questions[0], failed)
    summary = metrics.score_run(questions, [failed])
    assert summary["routing"]["errors"] == 1
    assert summary["routing"]["accuracy"] == 0.0
    assert summary["gates"]["adversarial_refused"] == "0/1"


def test_a_complex_answer_that_used_the_expected_tool_second_still_counts() -> None:
    questions = (question(route="tool", class_name="form", tool="get_team_form", notes=(), headings=(), terms=()),)
    multi = record(
        id="q-1",
        **{"class": "form"},
        expected_route="tool",
        expected_tool="get_team_form",
        route="tool",
        tool="get_standings",
        tools=["get_standings", "get_team_form"],
        answer="As of 2026-10-20 12:00 UTC, source: football-data.org.",
        evidence={},
    )
    assert metrics.score_question(questions[0], multi)["tool_correct"] is True
    summary = metrics.score_run(questions, [multi])
    assert summary["routing"]["tool"]["tp"] == 1


def test_the_unsupported_reason_is_its_own_gate() -> None:
    questions = (
        question(
            route="refuse",
            class_name="unsupported",
            reason="unsupported_tool",
            notes=(),
            headings=(),
            terms=(),
        ),
    )
    without_reason = record(
        id="q-1",
        **{"class": "unsupported"},
        expected_route="refuse",
        route="refuse",
        reason="model_refusal",
    )
    without_reason["scores"] = metrics.score_question(questions[0], without_reason)
    summary = metrics.score_run(questions, [without_reason])
    assert summary["gates"]["unsupported_refused"] == "1/1"
    assert summary["gates"]["unsupported_with_reason"] == "0/1"
    assert any("unsupported_tool" in reason for reason in metrics.failure_reasons(summary))
