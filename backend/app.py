"""The application: where the routers, the contract and the error shape are wired together.

Three deliberate choices live here.

**No generated OpenAPI document.** `openapi_url=None`, `docs_url=None`, `redoc_url=None`, and the
contract is served from the file at `/openapi.yaml` with Swagger UI pointing at it. FastAPI would
otherwise publish a spec derived from the code - a second definition of the same API that could
disagree with the reviewed one.

**Every failure is an `ErrorResponse`.** FastAPI answers a bad parameter with `422 {"detail": ...}` and
an unknown path with `404 {"detail": "Not Found"}`; neither is a shape this contract documents. The
handlers below replace both, and each one carries the request id that also goes into the
`X-Request-ID` header, so a user-visible error can be found in the log.

**The database is read-only and upstream is never touched.** `create_read_engine` connects as
`agent_readonly` where that role exists, and no request path imports the ingest client (`AGENTS.md`
rules 3 and 4).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Engine
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import __version__
from backend.contract import load_contract
from backend.db import create_admin_engine, create_read_engine, read_only
from backend.errors import ApiError, code_for_status
from backend.routers import admin, agent, competitions, evals, knowledge, matches, teams
from backend.routers import meta as meta_routes
from backend.routers import open as open_routes
from backend.settings import BackendSettings
from db.session import create_session_factory
from ingest.knowledge.embedding import Embedder, OllamaEmbedder
from telemetry import configure as configure_telemetry
from telemetry import instrument_app as instrument_telemetry
from telemetry import metrics as telemetry_metrics
from telemetry import shutdown as shutdown_telemetry

logger = logging.getLogger(__name__)
# Uvicorn configures the root logger at WARNING, so a child logger's INFO records are never created -
# and the OTel log handler on the root never sees the request line. The line is deliberately INFO (the
# per-request audit), so the level is set here rather than left to the server's default.
logger.setLevel(logging.INFO)

#: The API's own deadline for one embedding call. It sits under the MCP server's wait for the backend
#: (45 s), which sits under the gateway's wait for the MCP server (50 s); the ordering is asserted in
#: `tests/test_timeout_budget.py`. Indexing keeps the embedder's longer default because it is offline.
DEFAULT_EMBED_TIMEOUT = 40.0


def create_app(
    settings: BackendSettings | None = None,
    *,
    engine: Engine | None = None,
    embedder: Embedder | None = None,
) -> FastAPI:
    """Build the application.

    `engine` and `embedder` exist as injection points for tests: a unit test serves the same routes
    from a migrated SQLite file and a deterministic embedder, which is what makes the contract suite
    runnable with no stack at all. Production passes neither.
    """
    backend_settings = settings or BackendSettings.from_env()
    telemetry_on = configure_telemetry("hermes-backend", version=__version__)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.backend_settings = backend_settings
        app.state.contract = load_contract(backend_settings.contract_path)
        app.state.started_at = datetime.now(UTC)
        app.state.engine = engine if engine is not None else create_read_engine(backend_settings.db)
        app.state.session_factory = create_session_factory(app.state.engine)
        # The one write path exists only when the deployment configured an admin token. Without one
        # the app holds no write engine at all, which is a stronger statement than a 403.
        app.state.admin_engine = (
            create_admin_engine(backend_settings.db) if backend_settings.admin_enabled else None
        )
        app.state.admin_session_factory = (
            create_session_factory(app.state.admin_engine) if app.state.admin_engine is not None else None
        )
        app.state.embedder = embedder if embedder is not None else OllamaEmbedder(
            host=backend_settings.db.ollama_host,
            model=backend_settings.db.embedding_model,
            dim=backend_settings.db.embedding_dim,
            timeout=float(os.environ.get("OLLAMA_EMBED_TIMEOUT_SECONDS") or DEFAULT_EMBED_TIMEOUT),
        )
        logger.info(
            "api %s serving %s; read-only database role: %s; admin writes: %s",
            __version__,
            backend_settings.contract_path,
            read_only(backend_settings.db),
            "enabled" if backend_settings.admin_enabled else "disabled",
        )
        if not backend_settings.auth_enabled:
            logger.warning("API_AGENT_TOKEN is unset: every authenticated endpoint will answer 401")
        try:
            yield
        finally:
            if telemetry_on:
                shutdown_telemetry()
            # Close only what this app built. An injected engine and an injected embedder belong to
            # whoever passed them - a test that reuses one embedder across apps (the stack suite does,
            # it is module-scoped and points at Ollama) would otherwise find its client closed by the
            # first app that shut down, and every later query would fail inside the transport.
            if embedder is None:
                close = getattr(app.state.embedder, "close", None)
                if callable(close):
                    close()
            if engine is None:
                app.state.engine.dispose()
            if app.state.admin_engine is not None:
                app.state.admin_engine.dispose()

    app = FastAPI(
        title="Hermes Football API",
        version=__version__,
        description="Implements openapi.yaml; the contract is served verbatim at /openapi.yaml.",
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Attach an id, time the request, and log one line that cannot contain a message.

        The access log is disabled in Compose (`--no-access-log`) because uvicorn prints the query
        string, and `/search/knowledge?q=...` is user text. This line logs the route template instead,
        so a search for a note never becomes a log line or a Loki entry.
        """
        request.state.request_id = str(uuid.uuid4())
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        route = getattr(request.scope.get("route"), "path", None) or "unmatched"
        elapsed = time.perf_counter() - started
        attributes = {"route": route, "method": request.method, "status": str(response.status_code)}
        telemetry_metrics.HTTP_REQUESTS.add(1, attributes)
        telemetry_metrics.HTTP_DURATION.record(elapsed, {"route": route, "status": str(response.status_code)})
        logger.info(
            "request method=%s route=%s status=%s duration_ms=%.1f request_id=%s",
            request.method,
            route,
            response.status_code,
            elapsed * 1000,
            request.state.request_id,
        )
        return response

    def error_response(
        request: Request,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        body = {
            "error": {
                "code": code,
                "message": message,
                **({"details": details} if details else {}),
                "request_id": request_id,
            }
        }
        return JSONResponse(status_code=status_code, content=body, headers={"X-Request-ID": request_id})

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("api error %s on %s %s: %s", exc.code, request.method, request.url.path, exc.message)
        return error_response(
            request, status_code=exc.status_code, code=exc.code, message=exc.message, details=exc.details
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """A bad parameter is a 400 with the contract's error shape, not FastAPI's 422."""
        problems = [
            {"location": [str(part) for part in error.get("loc", ())], "message": error.get("msg", "")}
            for error in exc.errors()
        ]
        first = problems[0] if problems else {"location": [], "message": "invalid request"}
        where = ".".join(first["location"]) or "request"
        return error_response(
            request,
            status_code=400,
            code="invalid_parameter",
            message=f"{where}: {first['message']}",
            details={"errors": problems},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(
            request,
            status_code=exc.status_code,
            code=code_for_status(exc.status_code),
            message=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        # The message is deliberately generic: an unexpected error's text can carry a DSN or a token,
        # and this API's contract promises a message that is safe to show a user.
        return error_response(
            request,
            status_code=500,
            code="internal_error",
            message="Unexpected server error.",
        )

    instrument_telemetry(app)
    app.include_router(open_routes.router)
    app.include_router(meta_routes.router)
    app.include_router(competitions.router)
    app.include_router(matches.router)
    app.include_router(teams.router)
    app.include_router(knowledge.router)
    app.include_router(agent.router)
    app.include_router(evals.router)
    app.include_router(admin.router)
    return app


#: `uvicorn backend.app:app`. Configuration is read from the environment at import, which is what a
#: container wants; tests call `create_app(...)` with their own settings instead.
app = create_app()
