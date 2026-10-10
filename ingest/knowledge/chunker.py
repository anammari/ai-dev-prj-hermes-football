"""Turn one note into the passages that get embedded.

Deterministic by construction: the same file text always produces the same chunks in the same order,
which is what lets `R-F6.4` decide staleness from a content hash instead of asking a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ingest.knowledge.manifest import parse_front_matter

HEADING_RE = re.compile(r"^(#{1,4})\s+(.*\S)\s*$")

#: A passage longer than this is split at a paragraph boundary. Comfortably inside the model's
#: context, and small enough that a retrieved passage is a useful thing to put in front of a model.
MAX_CHARS = 1200
#: Sections with less text than this are labels and heading-only stubs, not answers.
MIN_CHARS = 80


@dataclass(frozen=True, slots=True)
class Chunk:
    heading: str
    ordinal: int
    text: str


def _hard_split(paragraph: str, limit: int) -> list[str]:
    """Cut a single paragraph that is longer than the limit, at the last space before it.

    Only reachable when one paragraph alone exceeds `limit`; the alternative is a passage the
    embedding model would truncate without telling anyone.
    """
    pieces: list[str] = []
    remaining = paragraph.strip()
    while len(remaining) > limit:
        cut = remaining.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _split_long(text: str, limit: int) -> list[str]:
    """Split at blank lines, never mid-paragraph unless a paragraph is itself too long."""
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in text.split("\n\n"):
        block = len(paragraph) + 2
        if current and size + block > limit:
            pieces.append("\n\n".join(current).strip())
            current, size = [], 0
        current.append(paragraph)
        size += block
    if current:
        pieces.append("\n\n".join(current).strip())

    bounded: list[str] = []
    for piece in pieces:
        bounded.extend(_hard_split(piece, limit) if len(piece) > limit else [piece])
    return [piece for piece in bounded if piece]


def chunk_markdown(text: str, *, max_chars: int = MAX_CHARS, min_chars: int = MIN_CHARS) -> list[Chunk]:
    """Split a note into passages at its headings.

    The heading of a passage is the nearest heading above it; a note's own title (the first `#`
    heading) labels the text that appears before any `##`.
    """
    _, body = parse_front_matter(text)

    sections: list[tuple[str, str]] = []
    heading = ""
    buffer: list[str] = []
    for line in body.splitlines():
        match = HEADING_RE.match(line)
        if match:
            sections.append((heading, "\n".join(buffer)))
            heading = match.group(2).strip()
            buffer = []
        else:
            buffer.append(line)
    sections.append((heading, "\n".join(buffer)))

    chunks: list[Chunk] = []
    ordinal = 0
    for heading, section in sections:
        section = section.strip()
        if len(section) < min_chars:
            continue
        for piece in _split_long(section, max_chars):
            if len(piece) < min_chars:
                continue
            chunks.append(Chunk(heading=heading or "untitled", ordinal=ordinal, text=piece))
            ordinal += 1
    return chunks
