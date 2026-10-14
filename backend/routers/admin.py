"""The two `/admin` operations the contract declares, which M3 deliberately does not implement.

They are *registered* rather than left to fall through a 404 handler, for two reasons: the route table
then still matches the contract path by path (so the drift test checks the whole document, not a
subset it was quietly told to skip), and a client gets a contract-shaped `404` that names the
milestone that owns the operation instead of a bare `{"detail": "Not Found"}`.

Why they are not in M3:

* `POST /admin/ingest-runs` would have to start an ingestion run. `AGENTS.md` rule 3 forbids calling
  upstream from request-handling code, and this service holds no upstream credential at all, so the
  trigger needs a queue that the `ingest` container drains - its own task, with its own migration.
* `PATCH /admin/agent-turns/{turnId}/review` is the dashboard's review button (M5). It is the only
  write in the contract, and adding it here would mean giving M3 a write engine and an admin token
  that nothing else uses yet.

`UNIMPLEMENTED` is the single list this module and `tests/test_api_contract.py` share, so the gap can
only ever be closed by deleting an entry, never by forgetting one.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from backend.deps import require_agent_token
from backend.errors import NotFound

# Authenticated like every other protected operation: a stub is still an endpoint, and "declared but
# unimplemented" must not become a path a stranger can probe without a token.
router = APIRouter(tags=["admin"], dependencies=[Depends(require_agent_token)])

#: operation id -> (the milestone that owns it, why it is not here)
UNIMPLEMENTED: dict[str, tuple[str, str]] = {
    "triggerIngestRun": (
        "M5",
        "needs the ingest container to own the run: rule 3 forbids upstream access from "
        "request-handling code, so the trigger requires a queue the scheduler drains",
    ),
    "reviewAgentTurn": (
        "M5",
        "the dashboard's review action; the only write in the contract, so it brings the admin "
        "token and a write engine with it",
    ),
}


def _not_yet(operation: str) -> NotFound:
    milestone, why = UNIMPLEMENTED[operation]
    return NotFound(
        f"{operation} is declared in openapi.yaml but not implemented in this milestone "
        f"({milestone}): {why}.",
        details={"operation": operation, "owner": milestone},
    )


@router.post("/admin/ingest-runs", operation_id="triggerIngestRun", status_code=202)
def trigger_ingest_run(payload: dict[str, Any] | None = None) -> None:
    raise _not_yet("triggerIngestRun")


@router.patch("/admin/agent-turns/{turnId}/review", operation_id="reviewAgentTurn")
def review_agent_turn(turnId: Annotated[UUID, Path()], payload: dict[str, Any]) -> None:  # noqa: N803
    raise _not_yet("reviewAgentTurn")
