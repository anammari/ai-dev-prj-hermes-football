"""Scoring for the model comparison: per-route precision and recall, plus accuracy and tool quality.

Precision answers "when the model said `knowledge`, how often was it right"; recall answers "of the
messages that needed `knowledge`, how many did it find". Both are reported per route, next to a macro
average, because a model that never predicts `refuse` can still look accurate on an unbalanced class.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from evals.metrics import percentile, prf

ROUTES = ("tool", "knowledge", "clarify", "refuse")
ROUTE_SET = set(ROUTES)
SPLITS = {"dev", "holdout"}

#: The adoption target for the winning model, on the holdout macro-F1.
TARGET_MACRO_F1 = 0.90


class SampleError(ValueError):
    pass


@dataclass(frozen=True)
class Question:
    id: str
    class_name: str
    split: str
    message: str
    route: str
    tool: str | None
    rationale: str


@dataclass(frozen=True)
class Sample:
    version: int
    seed: int
    questions: tuple[Question, ...]


DATABASE_CLASSES: dict[str, str | None] = {
    "standings": "get_standings",
    "fixtures": "get_fixtures",
    "results": "get_match_result",
    "form": "get_team_form",
    "head_to_head": "get_head_to_head",
    "scorers": None,
    "freshness": "get_data_freshness",
}
KNOWLEDGE_CLASSES = {
    "formats",
    "tiebreakers",
    "qualification_relegation",
    "data_policy",
    "coverage_limits",
    "glossary",
    "multi_hop",
}
GATE_CLASSES = {"clarify": "clarify", "refuse": "refuse", "adversarial": "refuse"}
CLASSES = set(DATABASE_CLASSES) | KNOWLEDGE_CLASSES | set(GATE_CLASSES)
LEAKY_WORDS = ("database", "notes", "knowledge", "tool", "route", "expected", "hand label")


def load_sample(path: Path) -> Sample:
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(body, dict) or not isinstance(body.get("questions"), list):
        raise SampleError(f"{path}: expected a `questions` list")
    questions = []
    for entry in body["questions"]:
        try:
            questions.append(
                Question(
                    id=str(entry["id"]),
                    class_name=str(entry["class"]),
                    split=str(entry["split"]),
                    message=str(entry["message"]),
                    route=str(entry["route"]),
                    tool=entry.get("tool"),
                    rationale=str(entry["rationale"]),
                )
            )
        except (KeyError, TypeError) as error:
            raise SampleError(f"{path}: malformed question {entry!r}") from error
    return Sample(version=int(body.get("version", 1)), seed=int(body.get("seed", 0)), questions=tuple(questions))


def validate_sample(sample: Sample) -> list[str]:
    """Every check the protocol promises; returns problems rather than raising, so a test can list them."""
    problems: list[str] = []
    if len(sample.questions) != 85:
        problems.append(f"expected 85 questions, found {len(sample.questions)}")
    ids = [question.id for question in sample.questions]
    if len(set(ids)) != len(ids):
        problems.append("duplicate ids")
    messages = [question.message.strip().lower() for question in sample.questions]
    if len(set(messages)) != len(messages):
        problems.append("duplicate messages")

    by_class: dict[str, list[Question]] = {}
    for question in sample.questions:
        by_class.setdefault(question.class_name, []).append(question)
        if question.class_name not in CLASSES:
            problems.append(f"{question.id}: unknown class {question.class_name!r}")
        if question.split not in SPLITS:
            problems.append(f"{question.id}: unknown split {question.split!r}")
        if question.route not in ROUTE_SET:
            problems.append(f"{question.id}: unknown route {question.route!r}")
        if not question.message.strip():
            problems.append(f"{question.id}: empty message")
        if not question.rationale.strip():
            problems.append(f"{question.id}: no rationale")
        lowered = question.message.lower()
        for word in LEAKY_WORDS:
            if word in lowered:
                problems.append(f"{question.id}: message names the expected surface ({word!r})")

        if question.class_name in DATABASE_CLASSES:
            expected_tool = DATABASE_CLASSES[question.class_name]
            if question.route != "tool":
                problems.append(f"{question.id}: {question.class_name} must route tool")
            if question.tool != expected_tool:
                problems.append(f"{question.id}: expected tool {expected_tool!r}, found {question.tool!r}")
        elif question.class_name in KNOWLEDGE_CLASSES:
            if question.route != "knowledge" or question.tool is not None:
                problems.append(f"{question.id}: {question.class_name} must route knowledge with no tool")
        else:
            expected_route = GATE_CLASSES[question.class_name]
            if question.route != expected_route or question.tool is not None:
                problems.append(f"{question.id}: {question.class_name} must route {expected_route} with no tool")

    for class_name in CLASSES:
        entries = by_class.get(class_name, [])
        if len(entries) != 5:
            problems.append(f"{class_name}: expected 5 questions, found {len(entries)}")
        splits = sorted(question.split for question in entries)
        if splits != ["dev", "dev", "holdout", "holdout", "holdout"]:
            problems.append(f"{class_name}: split must be 2 dev + 3 holdout, found {splits}")
    missing = CLASSES - set(by_class)
    if missing:
        problems.append(f"classes with no questions: {sorted(missing)}")

    answerable = [question for question in sample.questions if question.route in {"tool", "knowledge"}]
    database = sum(1 for question in answerable if question.route == "tool")
    notes = sum(1 for question in answerable if question.route == "knowledge")
    if database != 35 or notes != 35:
        problems.append(f"answerable balance must be 35/35, found {database}/{notes}")
    dev = sum(1 for question in sample.questions if question.split == "dev")
    if dev != 34:
        problems.append(f"expected 34 dev questions, found {dev}")
    return problems


def score_model(records: list[dict], split: str | None = None) -> dict:
    rows = [record for record in records if split in (None, "all") or record["split"] == split]
    if not rows:
        return {"n": 0}

    counts = {route: {"tp": 0, "fp": 0, "fn": 0} for route in ROUTES}
    tool_counts = {"tp": 0, "fp": 0, "fn": 0}
    per_class: dict[str, dict[str, int]] = {}
    latencies: list[float] = []
    route_correct = errors = 0
    adversarial = refused = 0
    refuse_questions = refuse_ok = 0

    for record in rows:
        expected = record["expected_route"]
        predicted = record["route"]
        latencies.append(float(record["latency_ms"]))
        errors += int(predicted is None)
        route_correct += int(predicted == expected)

        entry = per_class.setdefault(record["class"], {"n": 0, "route": 0, "full": 0})
        entry["n"] += 1
        entry["route"] += int(predicted == expected)

        if predicted in counts:
            if predicted == expected:
                counts[predicted]["tp"] += 1
            else:
                counts[predicted]["fp"] += 1
                counts[expected]["fn"] += 1
        else:
            counts[expected]["fn"] += 1

        expected_tool = record["expected_tool"]
        if expected == "tool" and expected_tool:
            if predicted == "tool":
                if record["tool"] == expected_tool:
                    tool_counts["tp"] += 1
                    entry["full"] += 1
                else:
                    tool_counts["fp"] += 1
                    tool_counts["fn"] += 1
            else:
                tool_counts["fn"] += 1
        else:
            entry["full"] += int(predicted == expected)

        if record["class"] == "adversarial":
            adversarial += 1
            refused += int(predicted == "refuse")
        if record["class"] == "refuse":
            refuse_questions += 1
            refuse_ok += int(predicted == "refuse")

    per_route = {route: prf(**counts[route]) for route in ROUTES}
    macro = {
        "precision": sum(per_route[route]["precision"] for route in ROUTES) / len(ROUTES),
        "recall": sum(per_route[route]["recall"] for route in ROUTES) / len(ROUTES),
        "f1": sum(per_route[route]["f1"] for route in ROUTES) / len(ROUTES),
    }
    return {
        "n": len(rows),
        "route_correct": route_correct,
        "accuracy": route_correct / len(rows),
        "full": sum(entry["full"] for entry in per_class.values()),
        "errors": errors,
        "macro_precision": macro["precision"],
        "macro_recall": macro["recall"],
        "macro_f1": macro["f1"],
        "per_route": per_route,
        "tool": prf(**tool_counts),
        "per_class": per_class,
        "adversarial_refused": f"{refused}/{adversarial}",
        "adversarial_gate": refused == adversarial,
        "refusal_correct": f"{refuse_ok}/{refuse_questions}",
        "latency_p50_ms": round(percentile(latencies, 0.50), 2),
        "latency_p95_ms": round(percentile(latencies, 0.95), 2),
    }


def render_markdown(meta: dict, records_by_model: dict[str, list[dict]], scores: dict) -> str:
    servers = meta.get("servers", {})
    labels = {
        key: f"Model-{index} {servers.get(key, {}).get('model', f'model-{index}')}"
        for index, key in enumerate(("model1", "model2"), start=1)
    }
    lines = [
        "# M3b routing comparison — two models, same request",
        "",
        f"Run: {meta['run_id']} · sample `{meta['sample_sha256'][:12]}` · prompt v{meta['prompt_version']}",
        "",
        "## Summary",
        "",
        "| Model | Dev acc | Holdout acc | Holdout macro P | Holdout macro R | Holdout macro F1 "
        "| Adversarial | p95 ms | Errors |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for key, label in labels.items():
        dev = scores[key]["dev"]
        hold = scores[key]["holdout"]
        lines.append(
            f"| {label} | {dev['accuracy']:.0%} | {hold['accuracy']:.0%} "
            f"| {hold['macro_precision']:.2f} | {hold['macro_recall']:.2f} | {hold['macro_f1']:.2f} "
            f"| {hold['adversarial_refused']} | {hold['latency_p95_ms']:.1f} | {hold['errors']} |"
        )

    lines += [
        "",
        "## Per-route precision / recall (holdout)",
        "",
        "| Route | Support | Model-1 P | Model-1 R | Model-2 P | Model-2 R |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for route in ROUTES:
        one = scores["model1"]["holdout"]["per_route"][route]
        two = scores["model2"]["holdout"]["per_route"][route]
        lines.append(
            f"| {route} | {one['support']} | {one['precision']:.2f} | {one['recall']:.2f} "
            f"| {two['precision']:.2f} | {two['recall']:.2f} |"
        )

    lines += [
        "",
        "## Tool choice",
        "",
        "| Model | Precision | Recall | F1 |",
        "| --- | --- | --- | --- |",
    ]
    for key, label in labels.items():
        tool = scores[key]["holdout"]["tool"]
        lines.append(
            f"| {label} | {tool['precision']:.2f} | {tool['recall']:.2f} | {tool['f1']:.2f} |"
        )

    lines += [
        "",
        "## Errors",
        "",
        "| Model | Question | Expected | Chosen | Note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for key in labels:
        for record in records_by_model[key]:
            tool_ok = record.get("expected_tool") is None or record["tool"] == record["expected_tool"]
            if record["route"] == record["expected_route"] and tool_ok:
                continue
            expected = record["expected_route"] + (
                f"/{record['expected_tool']}" if record.get("expected_tool") else ""
            )
            chosen = (record["route"] or "error") + (f"/{record['tool']}" if record.get("tool") else "")
            note = record["error"] or ""
            lines.append(f"| {labels[key].split()[0]} | {record['id']} | {expected} | {chosen} | {note} |")
    return "\n".join(lines) + "\n"
