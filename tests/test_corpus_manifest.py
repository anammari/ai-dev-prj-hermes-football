"""The corpus and its manifest, checked the way CI will check them (`R-F6.5`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.knowledge.manifest import (
    MANIFEST_NAME,
    QUESTION_CLASSES,
    ManifestError,
    check_corpus,
    load_manifest,
)


def test_corpus_matches_the_manifest(knowledge_dir: Path) -> None:
    """The one assertion that keeps AGENTS.md rule 9 true."""
    assert check_corpus(knowledge_dir) == []


def test_manifest_is_not_vacuous(knowledge_dir: Path) -> None:
    """A check over an empty corpus would pass happily and tell us nothing."""
    manifest = load_manifest(knowledge_dir)
    assert manifest.version >= 1
    assert manifest.notes, "the manifest lists no notes"
    for note in manifest.notes:
        assert note.path.is_file()
        assert note.source.strip(), f"{note.file}: no source citation"
        assert note.owner.strip(), f"{note.file}: no owner"
        assert set(note.question_classes) <= set(QUESTION_CLASSES)


def test_a_note_missing_from_the_manifest_fails(corpus_copy: Path) -> None:
    note = next(path for path in corpus_copy.rglob("*.md"))
    (corpus_copy / MANIFEST_NAME).write_text("version: 1\nnotes: []\n", encoding="utf-8")
    problems = check_corpus(corpus_copy)
    relative = note.relative_to(corpus_copy).as_posix()
    assert any(relative in problem and "not listed" in problem for problem in problems), problems


def test_a_stray_note_fails(corpus_copy: Path) -> None:
    (corpus_copy / "policy" / "stray.md").write_text("# Stray\n\nNobody declared this.\n", encoding="utf-8")
    problems = check_corpus(corpus_copy)
    assert any("stray.md" in problem and "not listed" in problem for problem in problems), problems


def test_front_matter_drift_fails(corpus_copy: Path) -> None:
    note = next(path for path in corpus_copy.rglob("*.md"))
    note.write_text(note.read_text(encoding="utf-8").replace("owner: ", "owner: someone-else #"), encoding="utf-8")
    problems = check_corpus(corpus_copy)
    assert any("owner does not match" in problem for problem in problems), problems


def test_an_entry_without_a_file_fails(corpus_copy: Path) -> None:
    note = next(path for path in corpus_copy.rglob("*.md"))
    note.unlink()
    problems = check_corpus(corpus_copy)
    assert any("not on disk" in problem for problem in problems), problems


def test_an_unknown_question_class_is_refused(corpus_copy: Path) -> None:
    import yaml

    path = corpus_copy / MANIFEST_NAME
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    body["notes"][0]["question_classes"] = ["vibes"]
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    with pytest.raises(ManifestError, match="unknown question classes"):
        load_manifest(corpus_copy)


def test_a_note_without_a_source_is_refused(corpus_copy: Path) -> None:
    import yaml

    path = corpus_copy / MANIFEST_NAME
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    for entry in body["notes"]:
        entry.pop("source", None)
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    with pytest.raises(ManifestError, match="missing source"):
        load_manifest(corpus_copy)
