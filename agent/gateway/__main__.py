"""Run the gateway: `python -m agent.gateway` (health on `GATEWAY_PORT`, default 8200)."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "agent.gateway.app:create_app",
        factory=True,
        host=os.environ.get("GATEWAY_HOST", "0.0.0.0"),
        port=int(os.environ.get("GATEWAY_PORT", "8200")),
        log_level=os.environ.get("GATEWAY_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
