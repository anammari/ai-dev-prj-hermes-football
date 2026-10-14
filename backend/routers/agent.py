"""`/agent/turns`: the conversation log the dashboard reads and the eval harness scores."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.contract import INT64_MAX, Contract
from backend.deps import get_contract, get_request_id, get_session, require_agent_token
from backend.meta import SOURCE_LOCAL, pagination, response_meta
from backend.services import turns as turns_service

router = APIRouter(tags=["agent"], dependencies=[Depends(require_agent_token)])


@router.get("/agent/turns", operation_id="listAgentTurns")
def list_agent_turns(
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_session)],
    contract: Annotated[Contract, Depends(get_contract)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=INT64_MAX)] = 0,
    grounded: bool | None = None,  # `?grounded=1|yes|true` all parse as Pydantic's lenient bool
    reviewStatus: str | None = None,  # noqa: N803 - the contract's parameter names are the API's
    since: datetime | None = None,
) -> dict:
    """Most recent first, with the tool calls behind each answer and whether it was grounded.

    The three routing columns (`route`, `route_source`, `route_confidence`) are served here; they
    joined the contract in v0.2.0 because rule 10 requires every turn to record which road it took.
    """
    review_status = contract.checked_enum("ReviewStatus", reviewStatus, field="reviewStatus")
    page = turns_service.list_agent_turns(
        session,
        limit=limit,
        offset=offset,
        grounded=grounded,
        review_status=review_status,
        since=since,
    )
    return {
        "data": page.data,
        "meta": response_meta(request_id=request_id, source=SOURCE_LOCAL, data_as_of=page.data_as_of),
        "pagination": pagination(limit=limit, offset=offset, total=page.total),
    }
