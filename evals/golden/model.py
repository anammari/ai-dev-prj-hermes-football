"""The golden question set: loading, label validation, and the corpus checks.

The set is a file, reviewed like code, and this module is the only reader of it. Two layers of
validation, deliberately separate:

* `validate_golden` is pure: counts, ids, duplicates, whether every class implies the right route and
  tool, whether a clarify or refuse question carries the fields it must not, and the label shapes.
* `validate_against_corpus` reads the notes and checks that every `expected_notes` path is a declared
  note and every `expected_headings` string is a real heading in one of that question's notes.

Keeping them apart means a unit test can validate a two-question sample without a corpus, and the
corpus check can fail with a message that quotes the note. Both run in `tests/test_golden_set.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ROUTES = ("tool", "knowledge", "clarify", "refuse")

TOOL_BY_CLASS: dict[str, str] = {
    "standings": "get_standings",
    "fixtures": "get_fixtures",
    "results": "get_match_result",
    "form": "get_team_form",
    "head_to_head": "get_head_to_head",
    "scorers": "get_top_scorers",
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
REFUSE_CLASSES = {
    "adversarial": "instruction_override",
    "fabricated": "fabricated_fact",
    "unsupported": "unsupported_tool",
}
CLASSES = set(TOOL_BY_CLASS) | KNOWLEDGE_CLASSES | {"clarify"} | set(REFUSE_CLASSES)

ROUTE_COUNTS = {"tool": 16, "knowledge": 16, "clarify": 8, "refuse": 8}
TOOL_COUNTS = {
    "get_standings": 3,
    "get_fixtures": 2,
    "get_match_result": 2,
    "get_team_form": 2,
    "get_head_to_head": 2,
    "get_top_scorers": 3,
    "get_data_freshness": 2,
}
TOTAL_QUESTIONS = sum(ROUTE_COUNTS.values())

#: A message must not name the label it is supposed to earn. Same list the routing holdout validates
#: with, because it is the same mistake: a question that says "notes" is not testing the model.
LEAKY_WORDS = ("database", "notes", "knowledge", "tool", "route", "expected", "hand label")

#: Words a term may not be: they appear in almost every answer, so requiring them measures nothing.
GENERIC_TERMS = {"data", "match", "team", "season", "the", "a", "an", "and", "of", "in", "is"}

HEADING_RE = re.compile(r"^(#{1,4})\s+(.*\S)\s*$", re.MULTILINE)


class GoldenError(ValueError):
    pass


@dataclass(frozen=True)
class Question:
    id: str
    class_name: str
    message: str
    route: str
    tool: str | None
    notes: tuple[str, ...]
    headings: tuple[str, ...]
    facts: tuple[str, ...]
    #: Each group is alternatives: the group is covered when any alternative appears in the answer.
    terms: tuple[tuple[str, ...], ...]
    reason: str | None
    rationale: str


@dataclass(frozen=True)
class GoldenSet:
    version: int
    created: str
    author: str
    questions: tuple[Question, ...]


def load_golden(path: Path) -> GoldenSet:
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(body, dict) or not isinstance(body.get("questions"), list):
        raise GoldenError(f"{path}: expected a `questions` list")
    questions = []
    for entry in body["questions"]:
        try:
            questions.append(
                Question(
                    id=str(entry["id"]),
                    class_name=str(entry["class"]),
                    message=str(entry["message"]),
                    route=str(entry["expected_route"]),
                    tool=entry.get("expected_tool"),
                    notes=tuple(str(note) for note in (entry.get("expected_notes") or [])),
                    headings=tuple(str(heading) for heading in (entry.get("expected_headings") or [])),
                    facts=tuple(str(fact) for fact in (entry.get("expected_facts") or [])),
                    terms=tuple(
                        tuple(str(alternative) for alternative in group)
                        for group in (entry.get("expected_terms") or [])
                    ),
                    reason=entry.get("expected_reason"),
                    rationale=str(entry.get("rationale") or ""),
                )
            )
        except (KeyError, TypeError) as error:
            raise GoldenError(f"{path}: malformed question {entry!r}") from error
    return GoldenSet(
        version=int(body.get("version", 1)),
        created=str(body.get("created", "")),
        author=str(body.get("author", "")),
        questions=tuple(questions),
    )


def validate_golden(golden: GoldenSet) -> list[str]:
    """Every label rule the set promises. Returns problems rather than raising, so a test can list them."""
    problems: list[str] = []
    questions = golden.questions
    if not golden.author.strip():
        problems.append("the set must name its author: independence is the point of a golden set")
    if len(questions) != TOTAL_QUESTIONS:
        problems.append(f"expected {TOTAL_QUESTIONS} questions, found {len(questions)}")
    ids = [question.id for question in questions]
    if len(set(ids)) != len(ids):
        problems.append("duplicate ids")
    messages = [question.message.strip().lower() for question in questions]
    if len(set(messages)) != len(messages):
        problems.append("duplicate messages")

    routes: dict[str, int] = {}
    tools: dict[str, int] = {}
    covered_notes: set[str] = set()
    for question in questions:
        routes[question.route] = routes.get(question.route, 0) + 1
        if question.route not in ROUTES:
            problems.append(f"{question.id}: unknown route {question.route!r}")
        if question.class_name not in CLASSES:
            problems.append(f"{question.id}: unknown class {question.class_name!r}")
            continue
        if not question.message.strip():
            problems.append(f"{question.id}: empty message")
        if not question.rationale.strip():
            problems.append(f"{question.id}: no rationale")
        lowered = question.message.lower()
        for word in LEAKY_WORDS:
            if word in lowered:
                problems.append(f"{question.id}: message names the expected surface ({word!r})")
        if len(question.facts) > 3:
            problems.append(f"{question.id}: at most 3 expected_facts, found {len(question.facts)}")
        if len(question.terms) > 4:
            problems.append(f"{question.id}: at most 4 term groups, found {len(question.terms)}")
        for group in question.terms:
            # Up to six alternatives in one group: a "did they win" outcome legitimately has
            # won/win/lost/loss/drew/draw, and splitting it would cap every correct answer below full
            # coverage. The cap exists to stop a group becoming "anything", not to punish synonyms.
            if not 1 <= len(group) <= 6:
                problems.append(f"{question.id}: a term group needs 1-6 alternatives, found {group!r}")
            for alternative in group:
                if not alternative.strip():
                    problems.append(f"{question.id}: empty term alternative")
                if alternative.strip().lower() in GENERIC_TERMS:
                    problems.append(f"{question.id}: {alternative!r} is too generic to require")

        if question.class_name in TOOL_BY_CLASS:
            expected_tool = TOOL_BY_CLASS[question.class_name]
            if question.route != "tool" or question.tool != expected_tool:
                problems.append(f"{question.id}: {question.class_name} must be tool/{expected_tool}")
            if question.notes or question.headings:
                problems.append(f"{question.id}: a tool question has no notes or headings")
            # A tool question may have no term groups: "how old is your data" names no entity that a
            # correct answer is obliged to contain, so completeness is not scored for it. Claiming a
            # score there would measure the fixture, not the answer.
            if question.reason is not None:
                problems.append(f"{question.id}: expected_reason is only for refuse questions")
            if question.tool:
                tools[question.tool] = tools.get(question.tool, 0) + 1
        elif question.class_name in KNOWLEDGE_CLASSES:
            if question.route != "knowledge" or question.tool is not None:
                problems.append(f"{question.id}: {question.class_name} must be knowledge with no tool")
            if not question.notes:
                problems.append(f"{question.id}: a knowledge question needs expected_notes")
            if not question.headings:
                problems.append(f"{question.id}: a knowledge question needs expected_headings")
            if not question.terms:
                problems.append(f"{question.id}: a knowledge question needs expected_terms")
            if question.reason is not None:
                problems.append(f"{question.id}: expected_reason is only for refuse questions")
            covered_notes.update(question.notes)
        elif question.class_name == "clarify":
            if question.route != "clarify" or question.tool is not None:
                problems.append(f"{question.id}: clarify must be clarify with no tool")
            if question.notes or question.terms or question.reason is not None:
                problems.append(f"{question.id}: a clarify question carries no evidence fields")
        else:
            expected_reason = REFUSE_CLASSES[question.class_name]
            if question.route != "refuse" or question.tool is not None:
                problems.append(f"{question.id}: {question.class_name} must be refuse with no tool")
            if question.reason != expected_reason:
                problems.append(f"{question.id}: {question.class_name} needs reason {expected_reason!r}")
            if question.notes or question.terms:
                problems.append(f"{question.id}: a refuse question carries no evidence fields")

    if routes != ROUTE_COUNTS:
        problems.append(f"route counts differ: expected {ROUTE_COUNTS}, found {routes}")
    if tools != TOOL_COUNTS:
        problems.append(f"tool counts differ: expected {TOOL_COUNTS}, found {tools}")
    if not covered_notes:
        problems.append("no knowledge question names a note")
    return problems


def note_headings(text: str) -> set[str]:
    """Every heading in a note, by the same rule the chunker uses to label a passage."""
    return {match.group(2).strip() for match in HEADING_RE.finditer(text)}


def validate_against_corpus(golden: GoldenSet, corpus_root: Path, declared: set[str]) -> list[str]:
    """The labels against the files: a note must be declared, and a heading must really exist there.

    `declared` is the manifest's file list, passed in rather than re-read here so this function does
    not know how a manifest is parsed.
    """
    problems: list[str] = []
    cache: dict[str, set[str]] = {}
    for question in golden.questions:
        for note in question.notes:
            if note not in declared:
                problems.append(f"{question.id}: {note} is not a declared note")
                continue
            if note not in cache:
                path = corpus_root / note
                cache[note] = note_headings(path.read_text(encoding="utf-8")) if path.exists() else set()
            if not cache[note]:
                problems.append(f"{question.id}: {note} has no headings")
        if question.headings and question.notes:
            available = set().union(*(cache.get(note, set()) for note in question.notes))
            for heading in question.headings:
                if heading not in available:
                    problems.append(f"{question.id}: {heading!r} is not a heading in {', '.join(question.notes)}")
    return problems
