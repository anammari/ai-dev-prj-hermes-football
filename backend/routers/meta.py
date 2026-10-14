"""`/meta/freshness` and `/meta/ingest-runs`: the freshness state and the evidence behind it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.contract import INT64_MAX, Contract
from backend.deps import get_contract, get_request_id, get_session, get_settings, require_agent_token
from backend.meta import pagination, response_meta
from backend.schemas import ingest_run
from backend.services import Page
from backend.services.freshness import freshness_report
from backend.settings import BackendSettings
from db.models import IngestRun

router = APIRouter(tags=["meta"], dependencies=[Depends(require_agent_token)])


@router.get("/meta/freshness", operation_id="getFreshness")
def get_freshness(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[BackendSettings, Depends(get_settings)],
) -> dict:
    """How old the data is, per competition. `FreshnessReport` carries its own `as_of` instead of the
    usual `meta` block, exactly as the contract describes it."""
    return freshness_report(session, settings)


@router.get("/meta/ingest-runs", operation_id="listIngestRuns")
def list_ingest_runs(
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_session)],
    contract: Annotated[Contract, Depends(get_contract)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=INT64_MAX)] = 0,
    status: str | None = None,
) -> dict:
    """One row per ingestion run, most recent first. The `status` filter is validated against the
    contract's own inline enum rather than a second copy of it."""
    status = contract.checked_property_enum("IngestRun", "status", status, field="status")

    filters = [] if status is None else [IngestRun.status == status]
    total = int(session.scalar(select(func.count()).select_from(IngestRun).where(*filters)) or 0)
    rows = list(
        session.scalars(
            select(IngestRun)
            .where(*filters)
            .order_by(IngestRun.started_at.desc(), IngestRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    page = Page(data=[ingest_run(row) for row in rows], total=total, data_as_of=None)
    return {
        "data": page.data,
        "meta": response_meta(request_id=request_id, source="hermes-football", data_as_of=page.data_as_of),
        "pagination": pagination(limit=limit, offset=offset, total=page.total),
    }
