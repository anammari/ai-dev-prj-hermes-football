"""The golden set is data, so it is tested like data: counts, labels, and the notes it names.

The set is authored independently of the harness (its header says so) and audited separately; these
tests are the mechanical half of that process. They would not catch a defensible-but-wrong route
label - the audit does that - but they do catch a duplicated message, a tool/route mismatch, a note
that is not in the manifest, a heading that does not exist, and a set that quietly loses a question.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from db.settings import REPO_ROOT
from evals.golden import model
from ingest.knowledge.manifest import load_manifest

CORPUS = REPO_ROOT / "hermes" / "agent-knowledge"
GOLDEN = REPO_ROOT / "evals" / "golden" / "golden-2026-10-26.yaml"


@pytest.fixture(scope="module")
def golden() -> model.GoldenSet:
    return model.load_golden(GOLDEN)


def test_the_set_satisfies_its_own_label_rules(golden) -> None:
    problems = model.validate_golden(golden)
    assert not problems, "\n".join(problems)


def test_every_expected_note_is_declared_and_every_heading_exists(golden) -> None:
    manifest = load_manifest(CORPUS)
    problems = model.validate_against_corpus(golden, CORPUS, set(manifest.by_file()))
    assert not problems, "\n".join(problems)


def test_the_set_covers_the_whole_corpus(golden) -> None:
    """A note no golden question asks about is a note nobody would notice if it disappeared."""
    manifest = load_manifest(CORPUS)
    covered = {note for question in golden.questions for note in question.notes}
    missing = set(manifest.by_file()) - covered
    assert not missing, f"notes with no golden question: {sorted(missing)}"


def test_the_set_names_its_author_and_creation_date(golden) -> None:
    assert golden.author.strip()
    assert golden.created.strip()
    assert golden.version >= 1


def test_the_validator_rejects_a_wrong_tool(golden) -> None:
    """The check has to be able to fail, or it is decoration. Swap a tool and the label rules bite."""
    broken = model.GoldenSet(
        version=golden.version,
        created=golden.created,
        author=golden.author,
        questions=tuple(
            question
            if question.id != "g-tool-standings-1"
            else model.Question(**{**question.__dict__, "tool": "get_fixtures"})
            for question in golden.questions
        ),
    )
    problems = model.validate_golden(broken)
    assert any("must be tool/get_standings" in problem for problem in problems), problems


def test_the_corpus_check_rejects_a_heading_that_does_not_exist(golden) -> None:
    manifest = load_manifest(CORPUS)
    broken = model.GoldenSet(
        version=golden.version,
        created=golden.created,
        author=golden.author,
        questions=tuple(
            question
            if question.route != "knowledge"
            else model.Question(
                **{**question.__dict__, "headings": ("A heading nobody wrote",)}
            )
            for question in golden.questions
        ),
    )
    problems = model.validate_against_corpus(broken, CORPUS, set(manifest.by_file()))
    assert problems and all("is not a heading in" in problem for problem in problems), problems


def test_the_golden_harness_never_reads_a_user_turn() -> None:
    """No code path may read the turn log to build an eval: the public review bot's traffic would end
    up in the scoreboard, which is a privacy change nobody signed off. A docstring may name the table;
    a query may not touch it."""
    import re

    pattern = re.compile(r"from db\.models import[^\n]*AgentTurn|text\([^)]*agent_turns|select\(AgentTurn")
    offenders = [
        path.name
        for path in (REPO_ROOT / "evals" / "golden").rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders


def test_the_set_file_is_not_empty_and_still_parseable() -> None:
    assert GOLDEN.exists()
    text = GOLDEN.read_text(encoding="utf-8")
    assert "questions:" in text
    assert len(Path(GOLDEN).read_text(encoding="utf-8").splitlines()) > 400
