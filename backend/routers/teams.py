"""`/teams/{teamId}` and `/teams/{teamId}/form`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from backend.contract import INT64_MAX, INT64_MIN, Contract
from backend.deps import get_contract, get_request_id, get_session, require_agent_token
from backend.meta import response_meta
from backend.services import teams as teams_service

router = APIRouter(prefix="/teams", tags=["teams"], dependencies=[Depends(require_agent_token)])


@router.get("/{teamId}", operation_id="getTeam")
def get_team(
    teamId: Annotated[int, Path(ge=INT64_MIN, le=INT64_MAX)],  # noqa: N803
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    """Team profile, including whether a squad is actually stored, so the agent can answer player
    questions only when it is."""
    answer = teams_service.get_team(session, teamId)
    return {"data": answer.data, "meta": response_meta(request_id=request_id, data_as_of=answer.data_as_of)}


@router.get("/{teamId}/form", operation_id="getTeamForm")
def get_team_form(
    teamId: Annotated[int, Path(ge=INT64_MIN, le=INT64_MAX)],  # noqa: N803
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_session)],
    contract: Annotated[Contract, Depends(get_contract)],
    competition: str | None = None,
    last: Annotated[int, Query(ge=1, le=20)] = 5,
) -> dict:
    """Last N settled matches as one object: W/D/L, points, goals and clean sheets, counted here
    rather than by the model that will talk about them."""
    competition = contract.checked_enum("CompetitionCode", competition, field="competition")
    answer = teams_service.get_team_form(session, teamId, competition=competition, last=last)
    return {"data": answer.data, "meta": response_meta(request_id=request_id, data_as_of=answer.data_as_of)}
