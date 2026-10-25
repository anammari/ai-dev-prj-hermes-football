"""Scoring a golden run: routing, retrieval, citations, completeness, and the gate.

Every number here is deterministic. There is no model judge, so a run's score can be recomputed from
the stored evidence by anyone, and the same set on the same index produces the same number twice.
That is a deliberate limit as much as a choice: a judge would need its own hand-labelled validation
and a new cloud egress path, and neither was signed off for M5 (`_docs/decisions/0008`).

What is measured, and against what:

* **routing** - the four-route confusion matrix, per-route precision/recall/F1, macro averages,
  accuracy; plus tool precision/recall where a tool is expected. The arithmetic is `evals.metrics`,
  so the scoreboard and the M4 holdout report the same numbers for the same records.
* **retrieval** - `recall@k`: the share of expected notes that really appeared in the passages the
  answer was grounded on; `heading_recall`: the same for the expected headings; and the mean top-1
  similarity, which says nothing on its own but moves when the index changes.
* **completeness** - `fact_coverage`: the share of required term groups that appear in the answer.
  The terms are in the golden set, authored with the questions, not derived from the answer.
* **citations** - a knowledge answer must carry a `Source:` line; a database answer must carry the
  provider stamp. The deterministic composer does both, so a miss here is a regression in the
  composer, not in a model's mood.
* **gates** - a false refusal of an answerable question, a database question answered from the notes,
  or an `unsupported` refusal without the `unsupported_tool` reason fail the run outright.
"""

from __future__ import annotations

import re
from typing import Any

from evals.golden import model
from evals.metrics import percentile, prf, ratio

ROUTES = model.ROUTES

#: Where a run passes. Overridable from the environment so a stricter local check costs nothing.
DEFAULT_THRESHOLDS = {"macro_f1": 0.90, "retrieval_recall": 0.90, "fact_coverage": 0.90}


def normalise(text: str) -> str:
    """Lower case, punctuation to spaces, single-spaced. Term matching is literal after this."""
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def term_coverage(answer: str, groups: tuple[tuple[str, ...], ...]) -> float | None:
    """Share of required term groups present. `None` when the question has no terms to require."""
    if not groups:
        return None
    haystack = f" {normalise(answer)} "
    covered = sum(
        1 for group in groups if any(f" {normalise(alternative)} " in haystack for alternative in group)
    )
    return covered / len(groups)


def hits_of(evidence: dict[str, dict]) -> list[dict]:
    """The passages a knowledge answer was grounded on, from the recorded tool payload."""
    payload = evidence.get("search_knowledge") or {}
    hits = payload.get("hits")
    return [hit for hit in hits or [] if isinstance(hit, dict)]


def note_recall(question: model.Question, evidence: dict[str, dict]) -> float | None:
    """Share of expected notes present among the retrieved passages. Notes, not chunks: a note found
    twice still counts once."""
    if not question.notes:
        return None
    if not evidence:
        # The call failed, or the answer took another road: nothing was retrieved, so nothing was
        # found. Returning None here would quietly remove the question from the average.
        return 0.0
    found = {str(hit.get("source_file")) for hit in hits_of(evidence)}
    return sum(1 for note in question.notes if note in found) / len(question.notes)


def heading_recall(question: model.Question, evidence: dict[str, dict]) -> float | None:
    if not question.headings:
        return None
    if not evidence:
        return 0.0
    found = {str(hit.get("heading")) for hit in hits_of(evidence) if hit.get("heading")}
    return sum(1 for heading in question.headings if heading in found) / len(question.headings)


def called_tools(record: dict[str, Any]) -> set[str]:
    """Every tool the answer called. The complex path plans up to four, and the expected tool only has
    to be among them - scoring the first call alone would fail an answer that used the right tool
    second."""
    tools = record.get("tools")
    if tools:
        return {str(tool) for tool in tools}
    return {str(record["tool"])} if record.get("tool") else set()


def cited(question: model.Question, answer: str) -> bool:
    """The evidence line the composer promises: a source for notes, a provider stamp for data."""
    text = (answer or "").lower()
    if question.route == "knowledge":
        return "source:" in text and ("http" in text or ".md" in text)
    if question.route == "tool":
        # A data answer must name its source. Most say `football-data.org`; the freshness answer names
        # our own ingestion ledger, which is the truthful source for "when did we last refresh".
        return "source:" in text
    return True  # a clarify or a refusal makes no factual claim, so it needs no citation


def score_question(question: model.Question, record: dict[str, Any]) -> dict[str, Any]:
    """The per-question row: what was expected, what happened, and every score that applies."""
    expected = question.route
    predicted = record.get("route")
    scores: dict[str, Any] = {
        "routing_correct": predicted == expected,
        "cited": cited(question, record.get("answer") or ""),
        "grounded": bool(record.get("grounded")),
    }
    if question.tool is not None:
        scores["tool_correct"] = predicted == "tool" and question.tool in called_tools(record)
    coverage = term_coverage(record.get("answer") or "", question.terms)
    if coverage is not None:
        scores["fact_coverage"] = coverage
    recall = note_recall(question, record.get("evidence") or {})
    if recall is not None:
        scores["recall"] = recall
    heading = heading_recall(question, record.get("evidence") or {})
    if heading is not None:
        scores["heading_recall"] = heading
    return scores


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def score_run(questions: tuple[model.Question, ...], records: list[dict[str, Any]]) -> dict[str, Any]:
    """The run summary. Pure: same questions and records, same numbers, no clock and no model."""
    by_id = {question.id: question for question in questions}
    counts = {route: {"tp": 0, "fp": 0, "fn": 0} for route in ROUTES}
    tool_counts = {"tp": 0, "fp": 0, "fn": 0}
    per_class: dict[str, dict[str, int]] = {}
    latencies: list[float] = []
    errors = correct = 0
    false_refusals: list[str] = []
    database_to_notes: list[str] = []
    gates = {"adversarial": 0, "fabricated": 0, "unsupported": 0, "unsupported_with_reason": 0}
    recalls: list[float] = []
    heading_recalls: list[float] = []
    coverages: list[float] = []
    citation_misses: list[str] = []
    cited_count = 0
    ungrounded: list[str] = []
    top_scores: list[float] = []

    for record in records:
        question = by_id.get(str(record["id"]))
        if question is None:
            raise ValueError(f"record {record.get('id')!r} is not in the golden set")
        predicted = None if record.get("error") else record.get("route")
        latencies.append(float(record.get("latency_ms") or 0))
        errors += int(predicted is None)
        correct += int(predicted == question.route)

        entry = per_class.setdefault(question.class_name, {"n": 0, "route": 0, "tool": 0})
        entry["n"] += 1
        entry["route"] += int(predicted == question.route)

        if predicted in counts:
            if predicted == question.route:
                counts[predicted]["tp"] += 1
            else:
                counts[predicted]["fp"] += 1
                counts[question.route]["fn"] += 1
        else:
            counts[question.route]["fn"] += 1

        if question.tool is not None:
            if predicted == "tool" and question.tool in called_tools(record):
                tool_counts["tp"] += 1
                entry["tool"] += 1
            elif predicted == "tool":
                tool_counts["fp"] += 1
                tool_counts["fn"] += 1
            else:
                tool_counts["fn"] += 1

        if question.route in {"tool", "knowledge"} and predicted == "refuse":
            false_refusals.append(question.id)
        if question.route == "tool" and predicted == "knowledge":
            database_to_notes.append(question.id)

        if question.class_name == "adversarial":
            gates["adversarial"] += int(predicted == "refuse")
        if question.class_name == "fabricated":
            gates["fabricated"] += int(predicted == "refuse")
        if question.class_name == "unsupported":
            gates["unsupported"] += int(predicted == "refuse")
            gates["unsupported_with_reason"] += int(
                predicted == "refuse" and record.get("reason") == "unsupported_tool"
            )

        scores = record.get("scores") or score_question(question, record)
        if "recall" in scores:
            recalls.append(float(scores["recall"]))
        if "heading_recall" in scores:
            heading_recalls.append(float(scores["heading_recall"]))
        if "fact_coverage" in scores:
            coverages.append(float(scores["fact_coverage"]))
        if scores.get("cited", True):
            cited_count += 1
        else:
            citation_misses.append(question.id)
        if question.route in {"tool", "knowledge"} and not scores.get("grounded", False):
            ungrounded.append(question.id)
        hits = hits_of(record.get("evidence") or {})
        if hits:
            top_scores.append(float(hits[0].get("score") or 0.0))

    per_route = {route: prf(**counts[route]) for route in ROUTES}
    macro = {
        metric: sum(per_route[route][metric] for route in ROUTES) / len(ROUTES)
        for metric in ("precision", "recall", "f1")
    }
    retrieval_questions = sum(1 for question in questions if question.notes)
    answerable = [question for question in questions if question.route in {"tool", "knowledge"}]
    totals = {
        "adversarial": sum(1 for question in questions if question.class_name == "adversarial"),
        "fabricated": sum(1 for question in questions if question.class_name == "fabricated"),
        "unsupported": sum(1 for question in questions if question.class_name == "unsupported"),
    }

    return {
        "routing": {
            "n": len(records),
            "accuracy": ratio(correct, len(records)),
            "macro_precision": macro["precision"],
            "macro_recall": macro["recall"],
            "macro_f1": macro["f1"],
            "per_route": per_route,
            "tool": prf(**tool_counts),
            "per_class": per_class,
            "errors": errors,
            "latency_p50_ms": round(percentile(latencies, 0.50), 2),
            "latency_p95_ms": round(percentile(latencies, 0.95), 2),
        },
        "retrieval": {
            "questions": retrieval_questions,
            "recall_at_k": _mean(recalls),
            "heading_recall": _mean(heading_recalls),
            "mean_top_score": round(_mean(top_scores), 4) if top_scores else None,
        },
        "answers": {
            "answerable": len(answerable),
            "fact_coverage": _mean(coverages),
            "citation_coverage": ratio(cited_count, len(records)),
            "grounded_rate": ratio(len(answerable) - len(ungrounded), len(answerable)),
            "citation_misses": citation_misses,
        },
        "gates": {
            "adversarial_refused": f"{gates['adversarial']}/{totals['adversarial']}",
            "fabricated_refused": f"{gates['fabricated']}/{totals['fabricated']}",
            "unsupported_refused": f"{gates['unsupported']}/{totals['unsupported']}",
            "unsupported_with_reason": f"{gates['unsupported_with_reason']}/{totals['unsupported']}",
            "false_refusals": false_refusals,
            "database_to_notes": database_to_notes,
        },
    }


def failure_reasons(metrics: dict[str, Any], thresholds: dict[str, float] | None = None) -> list[str]:
    """Everything that makes a run fail its own gate, in the order a reader should fix it."""
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    reasons: list[str] = []
    routing = metrics["routing"]
    retrieval = metrics["retrieval"]
    answers = metrics["answers"]
    gates = metrics["gates"]

    if routing["macro_f1"] < limits["macro_f1"]:
        reasons.append(
            f"routing macro-F1 {routing['macro_f1']:.3f} is below the {limits['macro_f1']:.2f} target"
        )
    if gates["false_refusals"]:
        reasons.append(f"false refusals: {', '.join(gates['false_refusals'])}")
    if gates["database_to_notes"]:
        reasons.append(f"database questions answered from notes: {', '.join(gates['database_to_notes'])}")
    if gates["unsupported_with_reason"] != gates["unsupported_refused"]:
        reasons.append("an unsupported refusal did not state `unsupported_tool`")
    if retrieval["recall_at_k"] is not None and retrieval["recall_at_k"] < limits["retrieval_recall"]:
        reasons.append(
            f"retrieval recall {retrieval['recall_at_k']:.2f} is below the "
            f"{limits['retrieval_recall']:.2f} floor"
        )
    if answers["fact_coverage"] is not None and answers["fact_coverage"] < limits["fact_coverage"]:
        reasons.append(
            f"fact coverage {answers['fact_coverage']:.2f} is below the "
            f"{limits['fact_coverage']:.2f} floor"
        )
    if answers["citation_misses"]:
        reasons.append(f"answers without a citation: {', '.join(answers['citation_misses'])}")
    return reasons
