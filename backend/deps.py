"""Request-scoped wiring: what a handler is allowed to reach, and how it authenticates.

FastAPI resolves these by name in handler signatures, which is what keeps the routes in
`backend/routers/` down to "validate, call a service, attach meta".

The one that carries a rule is `require_agent_token`. It is attached to every router except the three
open operations (`/health`, `/openapi.yaml`, `/docs`, exactly as the contract declares them with
`security: []`), and it **fails closed**: with no token configured, every authenticated endpoint
answers 401 instead of quietly opening up. Comparing with `hmac.compare_digest` on bytes means a
non-ASCII token from a stranger is a comparison, not a `TypeError` that turns into a 500.
"""

from __future__ import annotations

import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from backend.contract import Contract
from backend.errors import Unauthorized
from backend.settings import BackendSettings
from ingest.knowledge.embedding import Embedder


def get_settings(request: Request) -> BackendSettings:
    return request.app.state.backend_settings


def get_contract(request: Request) -> Contract:
    return request.app.state.contract


def get_request_id(request: Request) -> str:
    return request.state.request_id


def get_embedder(request: Request) -> Embedder:
    return request.app.state.embedder


def get_session(request: Request) -> Iterator[Session]:
    """A read-only session. The engine behind it logs in as `agent_readonly` where that role exists,
    and nothing here commits or writes."""
    factory = request.app.state.session_factory
    with factory() as session:
        yield session


def require_agent_token(
    request: Request, settings: Annotated[BackendSettings, Depends(get_settings)]
) -> None:
    """Bearer authentication, compared in constant time and failing closed.

    `agent_token` empty means no token is configured, which is *not* the same as "no token needed":
    every request is refused until a deployment supplies one. The scheme name is compared
    case-insensitively because RFC 7235 says so.
    """
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    expected = settings.agent_token
    authenticated = bool(expected) and scheme.lower() == "bearer" and hmac.compare_digest(
        token.strip().encode("utf-8"), expected.encode("utf-8")  # type: ignore[union-attr]
    )
    if not authenticated:
        raise Unauthorized(
            "A valid bearer token is required. Send 'Authorization: Bearer <token>'.",
            details={"scheme": "bearer"},
        )
