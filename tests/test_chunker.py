"""Chunking: deterministic, heading-aware, and bounded."""

from __future__ import annotations

from ingest.knowledge.chunker import chunk_markdown

NOTE = """---
title: A note
source: somewhere
---

# A note

Intro text that is long enough to be a passage in its own right, comfortably over the minimum
length the chunker applies to a section.

## First section

Some text about the first section, which is also long enough to survive the minimum-length filter
applied by the chunker.

## Empty section

too short
"""


def test_chunks_are_deterministic() -> None:
    assert chunk_markdown(NOTE) == chunk_markdown(NOTE)


def test_front_matter_is_not_indexed() -> None:
    text = " ".join(chunk.text for chunk in chunk_markdown(NOTE))
    assert "source: somewhere" not in text
    assert "---" not in text


def test_headings_label_their_sections() -> None:
    chunks = chunk_markdown(NOTE)
    assert [chunk.heading for chunk in chunks] == ["A note", "First section"]
    assert [chunk.ordinal for chunk in chunks] == [0, 1]


def test_short_sections_are_dropped() -> None:
    assert "too short" not in " ".join(chunk.text for chunk in chunk_markdown(NOTE))


def test_long_sections_are_split_without_losing_text() -> None:
    paragraph = "Sentence about a tiebreaker rule that runs a little long. " * 12
    note = f"# Title\n\n## Rules\n\n{paragraph}\n\n{paragraph}\n"
    chunks = chunk_markdown(note, max_chars=500)
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 500 for chunk in chunks)
    assert all(chunk.heading == "Rules" for chunk in chunks)
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    for word in ("tiebreaker", "rule"):
        assert sum(chunk.text.count(word) for chunk in chunks) == note.count(word)


def test_an_empty_note_yields_no_chunks() -> None:
    assert chunk_markdown("---\ntitle: empty\n---\n") == []
