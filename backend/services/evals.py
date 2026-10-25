"""Evaluation runs: the scoreboard, read back.

These are the only two read services that answer from tables the agent never writes. A run is stored
by `make eval` (the harness, with the owner URL) and read here through `agent_readonly`, which is the
same split the ingestion ledger uses: the writer owns the row, the API owns the presentation.

Two rules are encoded here rather than in the dashboard:

* a run is ordered by `started_at`, newest first, because the scoreboard's question is "what changed";
* `get_eval_run` returns the run and its results together, because a macro-F1 delta without the
  questions behind it is a number nobody can act on.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.errors import NotFound
from backend.schemas import eval_result, eval_run
from backend.services import Page
from db.models import EvalResult, EvalRun


def list_eval_runs(
    session: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    set_name: str | None = None,
    passed: bool | None = None,
) -> Page:
    filters = []
    if set_name is not None:
        filters.append(EvalRun.set_name == set_name)
    if passed is not None:
        filters.append(EvalRun.passed.is_(passed))

    total = int(session.scalar(select(func.count()).select_from(EvalRun).where(*filters)) or 0)
    rows = list(
        session.scalars(
            select(EvalRun)
            .where(*filters)
            .order_by(EvalRun.started_at.desc(), EvalRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return Page(data=[eval_run(row) for row in rows], total=total, data_as_of=None)


def get_eval_run(session: Session, run_id: str) -> tuple[dict, list[dict]]:
    row = session.get(EvalRun, run_id)
    if row is None:
        raise NotFound(f"No evaluation run with id {run_id}.", details={"runId": run_id})
    results = list(
        session.scalars(
            select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.question_id)
        )
    )
    return eval_run(row), [eval_result(result) for result in results]
