"""The one write in the API: a human review decision on an agent turn.

Rule 4 says the agent's data path is read-only, and it stays true: this module is not reachable from
any agent-facing operation, the MCP server and the gateway hold no admin credential, and the database
grant behind this session is UPDATE on `review_status` and `review_note` only
(`0004_evals_and_admin_review`).

It is a module of its own rather than three lines in the router for one reason: the security test that
proves "no backend module writes to the database" can then name exactly one exception, and a second
write appearing anywhere else is a failure rather than a review question. `tests/test_api_security.py`
also checks that the only columns this file writes are the two review columns.
"""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.errors import NotFound
from db.models import AgentTurn

#: The columns a review may touch. Named here so the test and the writer agree on the bound, and so a
#: future "just fix the answer while we are here" is a visible change to this tuple.
REVIEW_COLUMNS = ("review_status", "review_note")


def review_turn(session: Session, turn_id: str, *, status: str, note: str | None) -> AgentTurn:
    """Store the decision and return the row as stored.

    The existence check comes first so a missing turn is a `404` and not a silent no-op update; the
    re-read after the commit is what makes the response the stored state rather than the request
    echoed back.
    """
    if session.get(AgentTurn, turn_id) is None:
        raise NotFound(f"No agent turn with id {turn_id}.", details={"turnId": turn_id})

    session.execute(
        update(AgentTurn)
        .where(AgentTurn.id == turn_id)
        .values(review_status=status, review_note=note)
    )
    session.commit()

    stored = session.get(AgentTurn, turn_id, populate_existing=True)
    assert stored is not None  # the row existed a statement ago and this session holds the lock
    return stored
