"""The two `/admin` operations the contract declares: one implemented, one deliberately not.

**`PATCH /admin/agent-turns/{turnId}/review` is implemented in M5.** It is the dashboard's review
button and the only write in the contract, so it is also the only place where this API needs a write
engine. Three things keep it bounded:

* it authenticates with `API_ADMIN_TOKEN`, a token the agent never receives, and answers `403` when no
  admin token is configured - "disabled" is a state, not an unauthenticated door;
* it writes through the `agent_admin` role, whose grant is UPDATE on `review_status` and `review_note`
  and nothing else (`0004_evals_and_admin_review`);
* it writes `agent_turns` only. No football table, no DDL, no arbitrary SQL.

**`POST /admin/ingest-runs` stays a contract-shaped `404`, owned by a recorded post-M6 follow-up.**
A request handler must not start an upstream run (`AGENTS.md` rule 3); the trigger needs a queue the
`ingest` container drains, and a contract-visible queue state, which is a product/API change rather
than an operations one (`_docs/follow-ups.md`). `UNIMPLEMENTED` is the single list this
module and `tests/test_api_contract.py` share, so the gap can only ever be closed by deleting an
entry, never by forgetting one.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from backend.contract import Contract
from backend.deps import (
    get_admin_session,
    get_contract,
    get_request_id,
    require_admin_token,
    require_agent_token,
)
from backend.errors import InvalidParameter, NotFound
from backend.meta import SOURCE_LOCAL, response_meta
from backend.schemas import agent_turn
from backend.services import reviews

#: operation id -> (the milestone that owns it, why it is not here)
UNIMPLEMENTED: dict[str, tuple[str, str]] = {
    "triggerIngestRun": (
        "post-M6",
        "needs the ingest container to own the run, a queue-draining scheduler and a contract-visible "
        "queue state: rule 3 forbids upstream access from request-handling code. Recorded in "
        "_docs/follow-ups.md",
    ),
}

#: The contract's `note` bound. Enforced here rather than by Pydantic so the failure is the contract's
#: `400 invalid_parameter`, like every other out-of-contract value.
MAX_REVIEW_NOTE = 1000

router = APIRouter(tags=["admin"])


def _not_yet(operation: str) -> NotFound:
    milestone, why = UNIMPLEMENTED[operation]
    return NotFound(
        f"{operation} is declared in openapi.yaml but not implemented in this milestone "
        f"({milestone}): {why}.",
        details={"operation": operation, "owner": milestone},
    )


#: The trigger keeps the agent-token check: a stub is still an endpoint, and "declared but
#: unimplemented" must not become a path a stranger can probe without a token.
@router.post("/admin/ingest-runs", operation_id="triggerIngestRun", status_code=202)
def trigger_ingest_run(
    _payload: dict[str, Any] | None = None, _token: None = Depends(require_agent_token)
) -> None:
    raise _not_yet("triggerIngestRun")


@router.patch(
    "/admin/agent-turns/{turnId}/review",
    operation_id="reviewAgentTurn",
    dependencies=[Depends(require_admin_token)],
)
def review_agent_turn(
    turnId: Annotated[UUID, Path()],  # noqa: N803 - the contract's parameter names are the API's
    payload: dict[str, Any],
    request_id: Annotated[str, Depends(get_request_id)],
    session: Annotated[Session, Depends(get_admin_session)],
    contract: Annotated[Contract, Depends(get_contract)],
) -> dict:
    """Record the human decision: correct, flagged, wrong (or back to unreviewed).

    The row is re-read after the update so the response is the stored state, not the request echoed
    back; a review of a turn that does not exist is the contract's `404`, checked before any write.
    """
    raw_status = payload.get("reviewStatus")
    if raw_status is None:
        raise InvalidParameter("reviewStatus is required", details={"parameter": "reviewStatus"})
    status = contract.checked_enum("ReviewStatus", raw_status, field="reviewStatus")
    note = payload.get("note")
    if note is not None and not isinstance(note, str):
        raise InvalidParameter("note must be a string", details={"parameter": "note"})
    if isinstance(note, str) and len(note) > MAX_REVIEW_NOTE:
        raise InvalidParameter(
            f"note must be at most {MAX_REVIEW_NOTE} characters",
            details={"parameter": "note", "maxLength": MAX_REVIEW_NOTE},
        )

    turn_id = str(turnId)
    assert status is not None, "the presence check above makes a null status unreachable"
    stored = reviews.review_turn(session, turn_id, status=status, note=note)
    return {
        "data": agent_turn(stored),
        "meta": response_meta(request_id=request_id, source=SOURCE_LOCAL),
    }
