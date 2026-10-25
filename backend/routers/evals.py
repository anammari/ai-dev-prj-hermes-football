"""`/evals/runs`: the scoreboard the dashboard draws.

Read-only, like every other agent-facing operation. The runs are written by `make eval`, which is not
this service: rule 4 says the request path does not write data, and a scoreboard that could rewrite
its own history would not be evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from backend.contract import INT64_MAX
from backend.deps import get_request_id, get_session, require_agent_token
from backend.meta import SOURCE_LOCAL, pagination, response_meta
from backend.services import evals as evals_service

router = APIRouter(tags=["evals"], dependencies=[Depends(require_agent_token)])


@router.get("/evals/runs", operation_id="listEvalRuns")
def list_eval_runs(
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=INT64_MAX)] = 0,
    setName: str | None = None,  # noqa: N803 - the contract's parameter names are the API's
    passed: bool | None = None,
) -> dict:
    """Newest first, so the dashboard's first call is the run a reader cares about."""
    page = evals_service.list_eval_runs(session, limit=limit, offset=offset, set_name=setName, passed=passed)
    return {
        "data": page.data,
        "meta": response_meta(request_id=request_id, source=SOURCE_LOCAL, data_as_of=page.data_as_of),
        "pagination": pagination(limit=limit, offset=offset, total=page.total),
    }


@router.get("/evals/runs/{runId}", operation_id="getEvalRun")
def get_eval_run(
    runId: Annotated[UUID, Path()],  # noqa: N803 - the contract's parameter names are the API's
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_session)],
) -> dict:
    """The run and every question it scored. `data_as_of` is the run's own finish, not the request."""
    run, results = evals_service.get_eval_run(session, str(runId))
    finished = datetime.fromisoformat(run["finished_at"].replace("Z", "+00:00")) if run["finished_at"] else None
    return {
        "data": {"run": run, "results": results},
        "meta": response_meta(request_id=request_id, source=SOURCE_LOCAL, data_as_of=finished),
    }
