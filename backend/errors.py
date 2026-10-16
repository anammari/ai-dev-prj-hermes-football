"""One error shape, exactly as the contract documents it.

FastAPI's defaults disagree with this contract in two places a client would notice: a validation
failure answers `422` with `{"detail": [...]}`, and an unknown path answers `404` with
`{"detail": "Not Found"}`. Both are replaced in `backend/app.py` so that *every* failure a client can
see is an `ErrorResponse` with a stable machine-readable `code` - which is what the agent's refusal
behaviour and the dashboard's error states are built on (`R-F3.4`).

`data_not_available` deserves a note, because the contract also has `upstream_unavailable`. The
documented `503` for "the requested data is not in the database yet" says a client must report it as
*no data, never as no matches*; `upstream_unavailable` would say the provider was unreachable and
this API never talks to the provider (`AGENTS.md` rule 3). So this API answers `503` with
`data_not_available`, which is also the code the contract's own `ErrorResponse` example uses.
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """A failure with a documented status and a stable code."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class InvalidParameter(ApiError):
    status_code = 400
    code = "invalid_parameter"


class Unauthorized(ApiError):
    status_code = 401
    code = "unauthorized"


class Forbidden(ApiError):
    status_code = 403
    code = "forbidden"


class NotFound(ApiError):
    status_code = 404
    code = "not_found"


class Conflict(ApiError):
    status_code = 409
    code = "conflict"


class DataNotAvailable(ApiError):
    """Nothing has ever been ingested for this competition, and this API cannot fetch it."""

    status_code = 503
    code = "data_not_available"


#: Starlette raises plain `HTTPException`s for routing-level failures. They are mapped onto the
#: contract's vocabulary so a client never has to parse a shape the contract does not describe.
STATUS_CODES: dict[int, str] = {
    400: "invalid_parameter",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "invalid_parameter",
    409: "conflict",
    422: "invalid_parameter",
    503: "upstream_unavailable",
}


def code_for_status(status_code: int) -> str:
    if status_code in STATUS_CODES:
        return STATUS_CODES[status_code]
    return "invalid_parameter" if 400 <= status_code < 500 else "internal_error"
