"""`/search/knowledge`: retrieval over the hand-written corpus, for the questions a table cannot
answer."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.contract import Contract
from backend.deps import get_contract, get_embedder, get_request_id, get_session, get_settings, require_agent_token
from backend.meta import SOURCE_LOCAL, response_meta
from backend.services import knowledge as knowledge_service
from backend.settings import BackendSettings
from ingest.knowledge.embedding import Embedder

router = APIRouter(tags=["knowledge"], dependencies=[Depends(require_agent_token)])


@router.get("/search/knowledge", operation_id="searchKnowledge")
def search_knowledge(
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_session)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    settings: Annotated[BackendSettings, Depends(get_settings)],
    contract: Annotated[Contract, Depends(get_contract)],
    q: Annotated[str, Query(min_length=2, max_length=300)],
    k: Annotated[int, Query(ge=1, le=10)] = 4,
    competition: str | None = None,
    minScore: Annotated[float, Query(ge=0.0, le=1.0)] = 0.3,  # noqa: N803 - the contract's names
) -> dict:
    """Ranked passages with the file and heading to cite.

    An empty `data` is a real answer - the corpus does not cover the question - and `minScore` is
    applied rather than padded, which is what lets the agent say "not in my knowledge" instead of
    answering from the nearest irrelevant paragraph.
    """
    competition = contract.checked_enum("CompetitionCode", competition, field="competition")
    answer = knowledge_service.search(
        session,
        embedder,
        settings,
        q=q,
        k=k,
        competition=competition,
        min_score=minScore,
    )
    return {
        "data": answer.data["data"],
        "query": answer.data["query"],
        # A note is our own writing, not upstream data: `source` says so and `data_as_of` is null, as
        # the contract prescribes for derived data.
        "meta": response_meta(request_id=request_id, source=SOURCE_LOCAL, data_as_of=answer.data_as_of),
    }
