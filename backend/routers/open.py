"""The three unauthenticated operations, registered straight on the app.

`openapi.yaml` marks exactly these with `security: []`: the liveness probe a container healthcheck can
call without a secret, the contract itself, and Swagger UI. Everything else goes through
`require_agent_token`.

`/openapi.yaml` serves the *file*, not a document regenerated from the code. That is the whole point:
a reviewer can diff the deployed API against the repository, and the app cannot serve a shape it does
not implement. For the same reason FastAPI's own schema route is switched off in `backend/app.py`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend import __version__
from backend.deps import get_session, get_settings
from backend.settings import BackendSettings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meta"])


@router.get("/health", operation_id="getHealth")
def get_health(request: Request, session: Annotated[Session, Depends(get_session)]) -> dict:
    """Liveness. 200 while the process is up; the database is reported separately so a degraded
    stack is visible instead of silently green (a healthcheck that fails on a slow migration would
    restart the container for no reason)."""
    try:
        revision = session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
        database = {"status": "ok", "schema_revision": str(revision) if revision else "unknown"}
        status = "ok"
    except Exception as error:  # noqa: BLE001 - the probe reports, it does not propagate
        logger.warning("health: database unreachable: %s", error)
        database = {"status": "error", "schema_revision": "unknown"}
        status = "degraded"

    started = request.app.state.started_at
    return {
        "status": status,
        "version": __version__,
        "uptime_seconds": int((datetime.now(UTC) - started).total_seconds()),
        "db": database,
    }


@router.get("/openapi.yaml", operation_id="getOpenApiDocument", response_class=PlainTextResponse)
def get_openapi_document(settings: Annotated[BackendSettings, Depends(get_settings)]) -> PlainTextResponse:
    """The reviewed contract file, served verbatim."""
    return PlainTextResponse(
        settings.contract_path.read_text(encoding="utf-8"),
        media_type="application/yaml",
    )


@router.get("/docs", operation_id="getSwaggerUi", response_class=HTMLResponse)
def get_swagger_ui() -> HTMLResponse:
    """Swagger UI rendered from `/openapi.yaml`, so the interactive docs cannot disagree with the
    file the implementation is tested against."""
    return get_swagger_ui_html(openapi_url="/openapi.yaml", title="Hermes Football API")
