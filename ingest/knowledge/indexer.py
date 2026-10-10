"""Index the notes corpus into `knowledge_chunks`.

Deterministic and idempotent (`R-F6.4`): a file whose content hash still matches what is stored is
not re-embedded, so running this twice writes nothing the second time (`make ingest` twice must show
0 changed). Changing the embedding model or its dimension is a re-index, not an in-place edit, which
is why `--force` exists.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from db.models import EMBEDDING_DIM, KnowledgeChunk, new_id
from db.settings import Settings
from ingest.knowledge.chunker import chunk_markdown
from ingest.knowledge.embedding import Embedder
from ingest.knowledge.manifest import ManifestError, check_corpus, load_manifest


def content_hash(text: str) -> str:
    """Hash of the whole source file, which is what makes staleness a local decision."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


@dataclass(slots=True)
class IndexReport:
    files: int = 0
    indexed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    chunks_written: int = 0
    chunks_removed: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.indexed or self.removed or self.retired)

    def summary(self) -> str:
        return (
            f"{self.files} notes: {len(self.indexed)} indexed, {len(self.unchanged)} unchanged, "
            f"{len(self.retired)} retired, {len(self.removed)} removed from the index; "
            f"{self.chunks_written} chunks written, {self.chunks_removed} chunks deleted"
        )


def _delete_chunks(session: Session, source_file: str) -> int:
    result = session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_file == source_file))
    return int(result.rowcount or 0)


def _stored_hash(session: Session, source_file: str) -> str | None:
    return session.execute(
        select(KnowledgeChunk.content_hash).where(KnowledgeChunk.source_file == source_file).limit(1)
    ).scalar_one_or_none()


def index_corpus(
    session: Session,
    settings: Settings,
    *,
    embedder: Embedder,
    force: bool = False,
    only: set[str] | None = None,
) -> IndexReport:
    """Reconcile the index with the corpus. The caller commits."""
    problems = check_corpus(settings.knowledge_dir)
    if problems:
        raise ManifestError("corpus and manifest disagree:\n  " + "\n  ".join(problems))

    manifest = load_manifest(settings.knowledge_dir)
    report = IndexReport(files=len(manifest.notes))
    declared: set[str] = set()

    for note in manifest.notes:
        declared.add(note.file)
        if only is not None and note.file not in only:
            continue

        if note.status == "retired":
            report.chunks_removed += _delete_chunks(session, note.file)
            report.retired.append(note.file)
            continue

        text = note.path.read_text(encoding="utf-8")
        digest = content_hash(text)
        if not force and _stored_hash(session, note.file) == digest:
            report.unchanged.append(note.file)
            continue

        chunks = chunk_markdown(text)
        if not chunks:
            raise ManifestError(f"{note.file}: nothing indexable (no passage over the minimum length)")

        vectors = embedder.embed_documents([chunk.text for chunk in chunks], titles=[note.title] * len(chunks))
        widths = {len(vector) for vector in vectors}
        if widths != {EMBEDDING_DIM} or embedder.dim != EMBEDDING_DIM:
            raise RuntimeError(
                f"{note.file}: embedding width {sorted(widths)} from {embedder.model} does not match the "
                f"schema's vector({EMBEDDING_DIM}); the migration and the model must agree (_docs/decisions/0002)"
            )

        report.chunks_removed += _delete_chunks(session, note.file)
        for chunk, vector in zip(chunks, vectors, strict=True):
            session.add(
                KnowledgeChunk(
                    id=new_id(),
                    source_file=note.file,
                    heading=chunk.heading,
                    ordinal=chunk.ordinal,
                    chunk_text=chunk.text,
                    embedding=vector,
                    embedding_model=embedder.model,
                    embedding_dim=len(vector),
                    content_hash=digest,
                )
            )
        report.indexed.append(note.file)
        report.chunks_written += len(chunks)

    if only is None:
        indexed_files = set(session.scalars(select(KnowledgeChunk.source_file).distinct()))
        for stale in sorted(indexed_files - declared):
            report.chunks_removed += _delete_chunks(session, stale)
            report.removed.append(stale)
    return report


def search_knowledge(
    session: Session, embedder: Embedder, query: str, *, limit: int = 5
) -> list[tuple[KnowledgeChunk, float]]:
    """Closest passages to `query`, best first. Returns `(chunk, similarity)` with similarity in [0, 1].

    Postgres uses pgvector's cosine distance against the HNSW index. SQLite has no vector type, so the
    dev fallback scores in Python: same answer, slower, and only ever used in development.
    """
    vector = embedder.embed_query(query)
    if session.get_bind().dialect.name == "postgresql":
        distance = KnowledgeChunk.embedding.cosine_distance(vector)
        rows = session.execute(select(KnowledgeChunk, distance.label("distance")).order_by(distance).limit(limit)).all()
        return [(row[0], 1.0 - float(row[1])) for row in rows]

    chunks = list(session.scalars(select(KnowledgeChunk)))
    scored = [(chunk, _cosine(vector, chunk.embedding)) for chunk in chunks]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]
