"""`/matches/{matchId}` and `/head-to-head`.

Head-to-head is its own endpoint because the contract says so, and because the aggregate the provider
publishes is wrong: this API counts the meetings itself (`backend/services/matches.py`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from backend.contract import INT64_MAX, INT64_MIN, Contract
from backend.deps import get_contract, get_request_id, get_session, require_agent_token
from backend.meta import response_meta
from backend.services import matches as matches_service

router = APIRouter(tags=["matches"], dependencies=[Depends(require_agent_token)])


@router.get("/matches/{matchId}", operation_id="getMatch")
def get_match(
    matchId: Annotated[int, Path(ge=INT64_MIN, le=INT64_MAX)],  # noqa: N803
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    """One match: result or fixture, with the half-time score when the free tier supplies it."""
    answer = matches_service.get_match(session, matchId)
    return {"data": answer.data, "meta": response_meta(request_id=request_id, data_as_of=answer.data_as_of)}


@router.get("/head-to-head", operation_id="getHeadToHead")
def get_head_to_head(
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_session)],
    contract: Annotated[Contract, Depends(get_contract)],
    teamA: Annotated[  # noqa: N803
        int,
        Query(ge=INT64_MIN, le=INT64_MAX, description="Team id (as used by the provider)"),
    ],
    teamB: int,  # noqa: N803
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    competition: str | None = None,
) -> dict:
    """Recent meetings between two teams, with the record computed from the stored results.

    `summary` covers every settled meeting in the window and `matches` returns the most recent
    `limit` of them, so "who wins more often" is answered by the count and not by whatever fitted in
    the page.
    """
    competition = contract.checked_enum("CompetitionCode", competition, field="competition")
    answer = matches_service.head_to_head(session, teamA, teamB, limit=limit, competition=competition)
    return {"data": answer.data, "meta": response_meta(request_id=request_id, data_as_of=answer.data_as_of)}
