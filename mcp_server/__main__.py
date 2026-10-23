"""Run the MCP server: `python -m mcp_server` (port `MCP_PORT`, default 8100)."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "mcp_server.server:app",
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8100")),
        log_level=os.environ.get("MCP_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
