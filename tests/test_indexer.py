"""Indexing the corpus: end to end, idempotent, and honest about staleness (`R-F6.3`, `R-F6.4`)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import KnowledgeChunk
from db.settings import Settings
from ingest.knowledge.embedding import Embedder, FakeEmbedder
from ingest.knowledge.indexer import content_hash, index_corpus, search_knowledge
from ingest.knowledge.manifest import MANIFEST_NAME, ManifestError, load_manifest


def _count(session: Session) -> int:
    return len(session.scalars(select(KnowledgeChunk.id)).all())


def test_one_note_indexes_end_to_end(session: Session, settings: Settings, embedder: Embedder) -> None:
    """The M1 acceptance criterion: a note file goes in, a searchable chunk comes out."""
    manifest = load_manifest(settings.knowledge_dir)
    report = index_corpus(session, settings, embedder=embedder)
    session.commit()

    assert report.files == len(manifest.notes)
    assert set(report.indexed) == {note.file for note in manifest.notes}
    assert report.chunks_written >= 1
    assert _count(session) == report.chunks_written

    chunk = session.scalars(select(KnowledgeChunk)).first()
    assert chunk is not None
    assert chunk.source_file in {note.file for note in manifest.notes}
    assert chunk.embedding_model == embedder.model
    assert chunk.embedding_dim == 768
    assert len(chunk.embedding) == 768
    assert chunk.content_hash == content_hash((settings.knowledge_dir / chunk.source_file).read_text("utf-8"))
    assert chunk.chunk_text.strip()


def test_indexing_twice_writes_nothing_the_second_time(
    session: Session, settings: Settings, embedder: Embedder
) -> None:
    first = index_corpus(session, settings, embedder=embedder)
    session.commit()
    before = _count(session)

    second = index_corpus(session, settings, embedder=embedder)
    session.commit()

    assert second.chunks_written == 0
    assert second.indexed == []
    assert set(second.unchanged) == set(first.indexed)
    assert _count(session) == before


def test_force_re_embeds_everything(session: Session, settings: Settings, embedder: Embedder) -> None:
    index_corpus(session, settings, embedder=embedder)
    session.commit()

    forced = index_corpus(session, settings, embedder=embedder, force=True)
    session.commit()

    assert forced.chunks_written > 0
    assert forced.unchanged == []


def test_an_edited_note_is_re_embedded_without_duplicates(
    session: Session, settings: Settings, corpus_copy: Path, embedder: Embedder
) -> None:
    local = replace(settings, knowledge_dir=corpus_copy)
    index_corpus(session, local, embedder=embedder)
    session.commit()
    before = _count(session)

    note = next(path for path in corpus_copy.rglob("*.md"))
    note.write_text(
        note.read_text("utf-8")
        + "\n\n## Added later\n\nA paragraph added after the first index run, long enough to be kept.\n",
        encoding="utf-8",
    )
    report = index_corpus(session, local, embedder=embedder)
    session.commit()

    relative = note.relative_to(corpus_copy).as_posix()
    assert report.indexed == [relative]
    expected_unchanged = {entry.file for entry in load_manifest(corpus_copy).notes} - {relative}
    assert set(report.unchanged) == expected_unchanged
    before_for_note = len(
        session.scalars(select(KnowledgeChunk.id).where(KnowledgeChunk.source_file == relative)).all()
    )
    assert report.chunks_removed == before_for_note
    assert _count(session) == before - before_for_note + report.chunks_written

    keys = {(row.source_file, row.heading, row.ordinal) for row in session.scalars(select(KnowledgeChunk))}
    assert len(keys) == _count(session), "a chunk was written twice"


def test_a_retired_note_leaves_the_index(
    session: Session, settings: Settings, corpus_copy: Path, embedder: Embedder
) -> None:
    local = replace(settings, knowledge_dir=corpus_copy)
    index_corpus(session, local, embedder=embedder)
    session.commit()
    assert _count(session) > 0

    manifest_path = corpus_copy / MANIFEST_NAME
    manifest_path.write_text(
        manifest_path.read_text("utf-8").replace("status: reviewed", "status: retired"), encoding="utf-8"
    )
    report = index_corpus(session, local, embedder=embedder)
    session.commit()

    assert set(report.retired) == {note.file for note in load_manifest(corpus_copy).notes}
    assert _count(session) == 0


def test_a_note_removed_from_the_corpus_is_pruned_from_the_index(
    session: Session, settings: Settings, corpus_copy: Path, embedder: Embedder
) -> None:
    local = replace(settings, knowledge_dir=corpus_copy)
    index_corpus(session, local, embedder=embedder)
    session.commit()

    note = next(path for path in corpus_copy.rglob("*.md"))
    relative = note.relative_to(corpus_copy).as_posix()
    before = _count(session)
    removed_chunks = len(
        session.scalars(select(KnowledgeChunk.id).where(KnowledgeChunk.source_file == relative)).all()
    )
    note.unlink()
    import yaml

    manifest_body = yaml.safe_load((corpus_copy / MANIFEST_NAME).read_text("utf-8"))
    manifest_body["notes"] = [entry for entry in manifest_body["notes"] if entry["file"] != relative]
    (corpus_copy / MANIFEST_NAME).write_text(yaml.safe_dump(manifest_body, sort_keys=False), encoding="utf-8")
    report = index_corpus(session, local, embedder=embedder)
    session.commit()

    assert report.removed == [relative]
    assert _count(session) == before - removed_chunks
    assert session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.source_file == relative)).first() is None


def test_a_width_that_does_not_match_the_schema_is_refused(session: Session, settings: Settings) -> None:
    """`vector(768)` is pinned in the migration; a provider returning anything else must stop the run."""
    with pytest.raises(RuntimeError, match="does not match the schema"):
        index_corpus(session, settings, embedder=FakeEmbedder(dim=512))


def test_a_broken_corpus_is_refused_before_anything_is_written(
    session: Session, settings: Settings, corpus_copy: Path, embedder: Embedder
) -> None:
    (corpus_copy / "stray.md").write_text("# Stray\n\nUndeclared note.\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="not listed"):
        index_corpus(session, replace(settings, knowledge_dir=corpus_copy), embedder=embedder)
    assert _count(session) == 0


def test_search_returns_passages_with_scores(session: Session, settings: Settings, embedder: Embedder) -> None:
    index_corpus(session, settings, embedder=embedder)
    session.commit()

    hits = search_knowledge(session, embedder, "how old is the data", limit=3)
    assert 0 < len(hits) <= 3
    for chunk, score in hits:
        assert -1.0 <= score <= 1.0
        assert chunk.chunk_text.strip()


def test_search_on_an_empty_index_says_nothing(session: Session, settings: Settings, embedder: Embedder) -> None:
    """An empty corpus is an answer, not a crash (`R-F6.1`)."""
    assert search_knowledge(session, embedder, "anything") == []
