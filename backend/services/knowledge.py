"""Retrieval over the notes corpus (`search_knowledge`, `R-F6.2`/`R-F6.3`).

The index is the derived one M2 writes; this service embeds the query with the same local model and
ranks by cosine similarity. Two contract details shape it:

* `minScore` means "hits below it are dropped rather than padded", so an empty `data` array is a
  normal answer meaning *the corpus does not cover this* - the agent must be able to say so, and the
  endpoint must not pad a reply to look helpful.
* `competition` "boosts passages tagged with this competition". The tag lives in the corpus manifest
  (the note's `competitions`), not on the chunk row, so the manifest is read here. If it is missing or
  malformed the search still answers: a broken corpus should not take retrieval down, and the fact
  that it is broken is `make check-notes`'s business, not this endpoint's.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from backend.schemas import knowledge_hit
from backend.services import Answer
from backend.settings import BackendSettings
from ingest.knowledge.embedding import Embedder
from ingest.knowledge.indexer import search_knowledge

logger = logging.getLogger(__name__)

#: How many passages are pulled before re-ranking. The boost can lift a passage that similarity alone
#: would have left outside the top `k`, so the pool has to be wider than `k`; on a corpus of a few
#: dozen chunks this is simply "all of them".
PASSAGE_POOL = 30

#: A small, documented nudge for a passage whose note is tagged with the competition the caller asked
#: about. It is a tie-breaker, not a filter: it cannot lift a passage over the score threshold on its
#: own, because the threshold is applied after the boost.
COMPETITION_BOOST = 0.05


def search(
    session: Session,
    embedder: Embedder,
    settings: BackendSettings,
    *,
    q: str,
    k: int = 4,
    competition: str | None = None,
    min_score: float = 0.3,
) -> Answer:
    ranked = search_knowledge(session, embedder, q, limit=max(k, PASSAGE_POOL))
    tagged = _tags_by_file(settings)

    hits: list[tuple] = []
    for chunk, score in ranked:
        # Clamped before the threshold, not after: the contract's `score` is 0..1, and a cosine can be
        # negative on the SQLite path (Postgres/pgvector reports 0..1 already). Without this,
        # `minScore=0` would drop the very hits it means to keep.
        boosted = min(1.0, max(0.0, float(score)))
        if competition is not None and competition in tagged.get(chunk.source_file, ()):
            boosted = min(1.0, boosted + COMPETITION_BOOST)
        if boosted >= min_score:
            hits.append((chunk, boosted))
    hits.sort(key=lambda pair: pair[1], reverse=True)

    return Answer(
        data={"query": q, "data": [knowledge_hit(chunk, score) for chunk, score in hits[:k]]},
        # A knowledge passage carries no upstream timestamp: the contract says `data_as_of` is null for
        # derived data, and says so precisely for this case.
        data_as_of=None,
    )


def _tags_by_file(settings: BackendSettings) -> dict[str, tuple[str, ...]]:
    from ingest.knowledge.manifest import load_manifest

    try:
        manifest = load_manifest(settings.db.knowledge_dir)
    except Exception as error:  # a corpus problem must not become a retrieval outage
        logger.warning("knowledge manifest unavailable, competition boost disabled: %s", error)
        return {}
    return {note.file: note.competitions for note in manifest.notes}
