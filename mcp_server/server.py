"""MCP over HTTP: a minimal JSON-RPC server exposing the seven read-only football tools.

The protocol surface is the small part of MCP needed by a tool host: `initialize`, `tools/list` and
`tools/call` over one POST endpoint. It is HTTP rather than stdio so the server is its own container
with its own tests and scans (`_docs/product-spec.md` §4). No tool can write, run SQL, read a file or
call upstream; every call becomes a GET on the M3 API.

Authentication reuses the backend's agent token (`MCP_SERVER_TOKEN` if set, otherwise
`API_AGENT_TOKEN`). With neither configured, every call is refused rather than opened.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse

from mcp_server import __version__
from mcp_server.backend import Backend, BackendError
from mcp_server.tools import TOOLS, ToolContext, call

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "hermes-football-mcp"


def _server_token() -> str | None:
    return (os.environ.get("MCP_SERVER_TOKEN") or os.environ.get("API_AGENT_TOKEN") or "").strip() or None


def _error(request_id: object, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _result(request_id: object, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _tool_result(payload: dict, *, is_error: bool = False) -> dict:
    import json

    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": is_error,
    }


def create_app(*, backend: Backend | None = None, token: str | None = None) -> FastAPI:
    app = FastAPI(title="Hermes Football MCP", version=__version__, docs_url=None, redoc_url=None)
    app.state.backend = backend
    app.state.context = ToolContext(backend) if backend is not None else None
    app.state.token = token

    def context() -> ToolContext:
        if app.state.context is None:
            app.state.context = ToolContext(Backend(
                base_url=os.environ.get("BACKEND_BASE_URL", "http://backend:8000"),
                token=os.environ.get("API_AGENT_TOKEN"),
            ))
        return app.state.context

    def expected_token() -> str | None:
        return app.state.token if app.state.token is not None else _server_token()

    def authorised(header: str | None) -> bool:
        expected = expected_token()
        if not expected:
            return False
        return header == f"Bearer {expected}"

    def handle(message: object) -> dict | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, -32600, "invalid JSON-RPC request")
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(request_id, -32602, "params must be an object")

        if method == "initialize":
            return _result(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": __version__},
                },
            )
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None
        if method == "ping":
            return _result(request_id, {})
        if method == "tools/list":
            return _result(
                request_id,
                {
                    "tools": [
                        {"name": name, "description": description, "inputSchema": schema}
                        for name, (description, schema, _handler) in sorted(TOOLS.items())
                    ]
                },
            )
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or name not in TOOLS:
                return _error(request_id, -32602, f"unknown tool {name!r}")
            if not isinstance(arguments, dict):
                return _error(request_id, -32602, "arguments must be an object")
            try:
                payload = call(context(), name, arguments)
            except ValueError as error:
                return _error(request_id, -32602, str(error))
            except BackendError as error:
                payload = {"error": "backend_unavailable", "message": str(error)}
                return _result(request_id, _tool_result(payload, is_error=True))
            return _result(request_id, _tool_result(payload))
        return _error(request_id, -32601, f"method not found: {method}")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": SERVER_NAME, "version": __version__, "tools": len(TOOLS)}

    @app.post("/mcp")
    async def mcp(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        if not authorised(authorization):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(_error(None, -32700, "parse error"), status_code=200)
        if isinstance(body, list):
            responses = [response for response in (handle(item) for item in body) if response is not None]
            return JSONResponse(responses) if responses else Response(status_code=202)
        response = handle(body)
        if response is None:
            return Response(status_code=202)
        return JSONResponse(response)

    return app


app = create_app()
