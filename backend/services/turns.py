"""The agent turn log: what was asked, what was answered, how it was routed (`R-F6.6`, rule 10).

This is the dashboard's audit view and the evaluation harness's raw material, so it serves the three
routing columns M3 added to the contract. Nothing here writes: turns are recorded by the agent
(M4) through its own path, and this endpoint is how a human reads them back.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.schemas import agent_turn
from backend.services import Page
from db.models import AgentTurn


def list_agent_turns(
    session: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    grounded: bool | None = None,
    review_status: str | None = None,
    since: datetime | None = None,
) -> Page:
    filters = []
    if grounded is not None:
        filters.append(AgentTurn.grounded.is_(grounded))
    if review_status is not None:
        filters.append(AgentTurn.review_status == review_status)
    if since is not None:
        # A client that sends no offset means UTC: the contract's `date-time` allows both, and
        # comparing a naive value against Postgres' timestamptz would otherwise depend on the server's
        # session timezone.
        filters.append(AgentTurn.created_at >= (since if since.tzinfo is not None else since.replace(tzinfo=UTC)))

    total = int(session.scalar(select(func.count()).select_from(AgentTurn).where(*filters)) or 0)
    rows = list(
        session.scalars(
            select(AgentTurn)
            .where(*filters)
            .order_by(AgentTurn.created_at.desc(), AgentTurn.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return Page(data=[agent_turn(row) for row in rows], total=total, data_as_of=None)
