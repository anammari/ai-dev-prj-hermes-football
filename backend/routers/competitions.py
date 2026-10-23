"""`/competitions`, its league table, and its fixtures.

The matches operation lives here rather than with `/matches/{matchId}` because it shares the
`/competitions/{code}` path family; its contract tag is `matches`, which is what the route declares.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.contract import INT64_MAX, INT64_MIN, Contract
from backend.deps import get_contract, get_request_id, get_session, require_agent_token
from backend.meta import pagination, response_meta
from backend.schemas import competition
from backend.services import catalog
from backend.services import matches as matches_service
from backend.services import scorers as scorers_service
from backend.services import standings as standings_service

router = APIRouter(prefix="/competitions", dependencies=[Depends(require_agent_token)])


@router.get("", operation_id="listCompetitions", tags=["competitions"])
def list_competitions(
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    """Competitions ingestion has actually stored, with the coverage flags that let the agent answer
    "not covered" honestly instead of failing a lookup."""
    return {
        "data": [competition(row) for row in catalog.list_competitions(session)],
        "meta": response_meta(request_id=request_id, data_as_of=catalog.latest_data_as_of(session)),
    }


@router.get("/{code}/standings", operation_id="getStandings", tags=["competitions"])
def get_standings(
    code: str,
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_session)],
    contract: Annotated[Contract, Depends(get_contract)],
    season: Annotated[int | None, Query(ge=1990, le=2100)] = None,
    snapshot: date | None = None,
    matchday: Annotated[int | None, Query(ge=1, le=50)] = None,
) -> dict:
    """The most recent stored table, or the newest one on or before `snapshot`."""
    code = contract.checked_enum("CompetitionCode", code, field="code")  # type: ignore[assignment]
    answer = standings_service.get_standings(
        session, code, season=season, snapshot=snapshot, matchday=matchday
    )
    return {"data": answer.data, "meta": response_meta(request_id=request_id, data_as_of=answer.data_as_of)}


@router.get("/{code}/top-scorers", operation_id="getTopScorers", tags=["competitions"])
def get_top_scorers(
    code: str,
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_session)],
    contract: Annotated[Contract, Depends(get_contract)],
    season: Annotated[int | None, Query(ge=1990, le=2100)] = None,
    snapshot: date | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict:
    """The newest stored scorer snapshot for a competition, ordered by goals then assists."""
    code = contract.checked_enum("CompetitionCode", code, field="code")  # type: ignore[assignment]
    answer = scorers_service.get_top_scorers(session, code, season=season, snapshot=snapshot, limit=limit)
    return {"data": answer.data, "meta": response_meta(request_id=request_id, data_as_of=answer.data_as_of)}


@router.get("/{code}/matches", operation_id="listCompetitionMatches", tags=["matches"])
def list_competition_matches(
    code: str,
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_session)],
    contract: Annotated[Contract, Depends(get_contract)],
    season: Annotated[int | None, Query(ge=1990, le=2100)] = None,
    matchday: Annotated[int | None, Query(ge=1, le=60)] = None,
    dateFrom: date | None = None,  # noqa: N803 - the contract's parameter names are the API's
    dateTo: date | None = None,  # noqa: N803
    teamId: Annotated[int | None, Query(ge=INT64_MIN, le=INT64_MAX)] = None,  # noqa: N803
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=INT64_MAX)] = 0,
) -> dict:
    """Fixtures and results for a competition, ordered by kickoff. Filters compose."""
    code = contract.checked_enum("CompetitionCode", code, field="code")  # type: ignore[assignment]
    status = contract.checked_enum("MatchStatus", status, field="status")
    page = matches_service.list_competition_matches(
        session,
        code,
        season=season,
        matchday=matchday,
        date_from=dateFrom,
        date_to=dateTo,
        team_id=teamId,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "data": page.data,
        "meta": response_meta(request_id=request_id, data_as_of=page.data_as_of),
        "pagination": pagination(limit=limit, offset=offset, total=page.total),
    }
