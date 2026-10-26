"""The three deadlines around a knowledge search must nest.

A notes answer crosses three waits: the API embeds the query locally, the MCP server waits for that
API response, and the gateway waits for the MCP server. If the middle wait is shorter than the work it
is waiting for, the answer is abandoned while it is about to succeed - which is exactly what the
retained stack did at 15 s against a 13-18.5 s search (`_docs/ai-usage-report.md` S16/S17).

Keeping the numbers in one test rather than trusting three scattered literals is the point: raising
the embedding deadline without raising the two waits above it fails here.
"""

from __future__ import annotations

from agent.config import AgentSettings
from backend.app import DEFAULT_EMBED_TIMEOUT
from mcp_server.backend import DEFAULT_BACKEND_TIMEOUT
from mcp_server.server import backend_timeout


def test_the_embedding_backend_and_gateway_deadlines_nest() -> None:
    gateway_timeout = AgentSettings().mcp_timeout
    assert DEFAULT_EMBED_TIMEOUT < DEFAULT_BACKEND_TIMEOUT < gateway_timeout


def test_the_gateway_timeout_is_configurable_from_the_environment() -> None:
    settings = AgentSettings.from_env({"MCP_TIMEOUT_SECONDS": "70"})
    assert settings.mcp_timeout == 70.0


def test_the_mcp_backend_timeout_is_configurable_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("MCP_BACKEND_TIMEOUT_SECONDS", "64")
    assert backend_timeout() == 64.0


def test_the_mcp_backend_timeout_falls_back_to_the_nested_default(monkeypatch) -> None:
    monkeypatch.delenv("MCP_BACKEND_TIMEOUT_SECONDS", raising=False)
    assert backend_timeout() == DEFAULT_BACKEND_TIMEOUT
