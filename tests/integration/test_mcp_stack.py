"""The MCP tools against the running M3 API: the read-only surface, end to end."""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from mcp_server.backend import Backend
from mcp_server.resolver import Registry
from mcp_server.server import create_app
from mcp_server.tools import ToolContext, get_data_freshness, get_standings, get_top_scorers, search_knowledge

pytestmark = pytest.mark.integration

BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://backend:8000")
TOKEN = os.environ.get("API_AGENT_TOKEN") or ""
MCP_TOKEN = os.environ.get("MCP_SERVER_TOKEN") or TOKEN
NEEDS_DATA = "this database holds no ingested standings: run `make ingest` or use the retained volume"


@pytest.fixture(scope="module")
def backend() -> Backend:
    if not TOKEN:
        pytest.skip("API_AGENT_TOKEN is unset: the tool server would refuse to call the API")
    return Backend(base_url=BASE_URL, token=TOKEN)


@pytest.fixture(scope="module")
def context(backend: Backend) -> ToolContext:
    return ToolContext(backend)


def test_the_registry_reads_the_stored_tables(backend: Backend) -> None:
    registry = Registry.load(backend)
    if not registry.competitions:
        pytest.skip(NEEDS_DATA)
    assert {competition.code for competition in registry.competitions} >= {"PL", "SA", "BL1"}
    assert len(registry.teams) > 100
    assert registry.find_team("Arsenal") is not None


def test_standings_answer_names_the_competition_and_the_data_time(context: ToolContext) -> None:
    result = get_standings(context, "where are Arsenal in the table?")
    if result.get("error"):
        pytest.skip(NEEDS_DATA)
    assert result["competition"]["code"] == "PL"
    assert result["focus"] is not None
    assert result["data_as_of"]


def test_freshness_is_served_for_every_stored_competition(context: ToolContext) -> None:
    result = get_data_freshness(context, "")
    if len(result["competitions"]) < 10:
        pytest.skip(NEEDS_DATA)
    assert result["as_of"]


def test_top_scorers_are_served_from_the_stored_snapshot(context: ToolContext) -> None:
    result = get_top_scorers(context, "who is the top scorer in the Premier League?", limit=5)
    if result.get("error"):
        pytest.skip(NEEDS_DATA)
    assert result["competition"]["code"] == "PL"
    assert result["scorers"]
    assert result["scorers"][0]["goals"] >= result["scorers"][-1]["goals"]
    assert result["data_as_of"]


def test_the_seed_note_is_retrievable_through_the_tool(context: ToolContext) -> None:
    result = search_knowledge(context, "why are the scores delayed and how old is the data")
    if result["count"] < 1:
        pytest.skip("the corpus is not indexed in this database: run `make index-notes`")
    assert result["hits"][0]["source_file"].startswith("policy/")


def test_the_mcp_endpoint_serves_the_same_tool_over_http(backend: Backend) -> None:
    client = TestClient(create_app(backend=backend, token=TOKEN))
    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {MCP_TOKEN}"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_standings", "arguments": {"query": "where are Arsenal?"}},
        },
    )
    body = response.json()
    assert body["result"]["isError"] is False
    payload = json.loads(body["result"]["content"][0]["text"])
    if payload.get("error"):
        pytest.skip(NEEDS_DATA)
    assert payload["competition"]["code"] == "PL"


def test_the_running_mcp_container_answers_over_http() -> None:
    import httpx

    url = os.environ.get("MCP_BASE_URL", "http://mcp-server:8100")
    try:
        health = httpx.get(f"{url}/health", timeout=5)
    except httpx.HTTPError as error:
        pytest.skip(f"the mcp-server container is not reachable at {url}: {error}")
    assert health.status_code == 200
    assert health.json()["tools"] == 8

    response = httpx.post(
        f"{url}/mcp",
        headers={"Authorization": f"Bearer {MCP_TOKEN}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        timeout=10,
    )
    assert response.status_code == 200
    assert len(response.json()["result"]["tools"]) == 8
