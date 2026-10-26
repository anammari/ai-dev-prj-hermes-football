"""A small MCP client for the tool server.

The gateway calls the MCP server over HTTP, so the tool surface stays a separate process with its own
tests and its own read-only credentials. The client understands the three methods the server exposes
and parses a tool result's JSON text; a tool error becomes an exception the composer can answer
honestly.
"""

from __future__ import annotations

import itertools
import json

import httpx


class MCPError(RuntimeError):
    """The tool server is unreachable or answered outside the MCP shape."""


class MCPToolError(RuntimeError):
    """A tool ran and reported an error (for example the backend is down)."""


class MCPClient:
    def __init__(self, url: str, token: str | None, timeout: float = 50.0) -> None:
        if not token:
            raise MCPError("MCP_SERVER_TOKEN/API_AGENT_TOKEN is unset: refusing to call the tool server")
        self.url = url
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._ids = itertools.count(1)
        self._initialised = False

    def close(self) -> None:
        self._client.close()

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method}
        if params is not None:
            payload["params"] = params
        try:
            response = self._client.post(self.url, json=payload)
        except httpx.HTTPError as error:
            raise MCPError(f"tool server request failed: {error}") from error
        if response.status_code != 200:
            raise MCPError(f"tool server HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as error:
            raise MCPError("tool server answered a non-JSON body") from error
        if "error" in body:
            raise MCPError(str(body["error"].get("message") or body["error"]))
        result = body.get("result")
        if not isinstance(result, dict):
            raise MCPError("tool server answered no result object")
        return result

    def initialise(self) -> None:
        if self._initialised:
            return
        self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "hermes-football-gateway", "version": "0.1.0"},
            },
        )
        self._initialised = True

    def tools(self) -> list[dict]:
        self.initialise()
        return list(self._rpc("tools/list").get("tools") or [])

    def call(self, name: str, arguments: dict) -> dict:
        self.initialise()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content") or []
        if not content or content[0].get("type") != "text":
            raise MCPError("tool result has no text content")
        text = content[0].get("text") or "{}"
        if result.get("isError"):
            raise MCPToolError(text)
        try:
            payload = json.loads(text)
        except ValueError as error:
            raise MCPError("tool result text is not JSON") from error
        if not isinstance(payload, dict):
            raise MCPError("tool result is not an object")
        return payload
