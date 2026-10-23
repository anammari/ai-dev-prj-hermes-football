"""The MCP surface: protocol shape, auth, and each tool against a fake backend."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from mcp_server.backend import BackendError, Envelope
from mcp_server.server import create_app
from mcp_server.tools import (
    ToolContext,
    get_data_freshness,
    get_fixtures,
    get_head_to_head,
    get_match_result,
    get_standings,
    get_team_form,
    get_top_scorers,
    search_knowledge,
)

TOKEN = "test-mcp-token"


def _row(position: int, team_id: int, name: str, points: int = 10) -> dict:
    return {
        "position": position,
        "team": {"id": team_id, "name": name},
        "played": 6,
        "points": points,
        "goal_difference": 4,
        "form": "W,D,W,L,W",
    }


class FakeBackend:
    def __init__(self) -> None:
        self.standings_calls = 0

    def competitions(self) -> list[dict]:
        return [
            {"code": "PL", "name": "Premier League", "type": "LEAGUE"},
            {"code": "SA", "name": "Serie A", "type": "LEAGUE"},
        ]

    def standings(self, code: str) -> Envelope:
        self.standings_calls += 1
        if code == "SA":
            table = [_row(1, 10, "Napoli FC", 15)]
        else:
            table = [
                _row(1, 65, "Manchester City FC", 18),
                _row(2, 57, "Arsenal FC", 15),
                _row(3, 61, "Chelsea FC", 10),
                _row(5, 64, "Liverpool FC", 9),
                _row(6, 62, "Everton FC", 8),
                _row(7, 67, "Newcastle United FC", 8),
                _row(8, 397, "Brighton & Hove Albion FC", 7),
                _row(18, 73, "Tottenham Hotspur FC", 3),
                _row(19, 1044, "AFC Bournemouth", 3),
            ]
        return Envelope(
            data={"competition": {"code": code}, "season": 2026, "table": table},
            meta={"data_as_of": "2026-10-13T02:02:15Z"},
        )

    def matches(self, code: str, **params: object) -> Envelope:
        now = datetime.now(UTC)
        matches = [
            {
                "id": 1,
                "utc_date": (now - timedelta(days=3)).isoformat().replace("+00:00", "Z"),
                "status": "FINISHED",
                "competition": {"code": "PL", "name": "Premier League"},
                "home_team": {"id": 57, "name": "Arsenal FC"},
                "away_team": {"id": 61, "name": "Chelsea FC"},
                "score": {"full_time": {"home": 2, "away": 1}},
                "last_updated": "2026-10-12T00:20:33Z",
            },
            {
                "id": 2,
                "utc_date": (now + timedelta(days=4)).isoformat().replace("+00:00", "Z"),
                "status": "TIMED",
                "competition": {"code": "PL", "name": "Premier League"},
                "home_team": {"id": 57, "name": "Arsenal FC"},
                "away_team": {"id": 64, "name": "Liverpool FC"},
                "score": {"full_time": {"home": None, "away": None}},
                "last_updated": "2026-10-12T00:20:33Z",
            },
        ]
        team_id = params.get("teamId")
        if team_id is not None:
            matches = [m for m in matches if team_id in {m["home_team"]["id"], m["away_team"]["id"]}]
        return Envelope(data=matches, meta={"data_as_of": "2026-10-12T00:20:33Z"})

    def top_scorers(self, code: str, *, season: int | None = None, limit: int = 10) -> Envelope:
        return Envelope(
            data={
                "competition": {"code": code, "name": "Premier League"},
                "season": 2026,
                "snapshot": "2026-10-22",
                "scorers": [
                    {
                        "player": {"id": 1001, "name": "Bukayo Saka"},
                        "team": {"id": 57, "name": "Arsenal FC"},
                        "goals": 5,
                        "assists": 2,
                        "penalties": 1,
                        "played": 7,
                    }
                ],
            },
            meta={"data_as_of": "2026-10-22T00:00:00Z"},
        )

    def match(self, match_id: int) -> Envelope:
        return Envelope(data={}, meta={})

    def team_form(self, team_id: int, *, competition: str | None = None, last: int = 5) -> Envelope:
        return Envelope(
            data={
                "team": {"id": team_id, "name": "Arsenal FC"},
                "window": {"matches_considered": 5},
                "summary": {"played": 5, "won": 4, "drawn": 0, "lost": 1, "points": 12, "clean_sheets": 2},
                "matches": [],
            },
            meta={"data_as_of": "2026-10-12T00:20:33Z"},
        )

    def head_to_head(self, team_a: int, team_b: int, *, limit: int = 5) -> Envelope:
        return Envelope(
            data={
                "teams": [{"id": team_a}, {"id": team_b}],
                "summary": {"played": 4, "team_a_wins": 3, "draws": 1, "team_b_wins": 0},
                "matches": [],
            },
            meta={"data_as_of": "2026-10-12T00:20:33Z"},
        )

    def search_knowledge(self, query: str, *, k: int = 3, min_score: float = 0.25) -> Envelope:
        if "playoff" in query:
            return Envelope(
                data=[
                    {
                        "source_file": "formats/championship-playoffs.md",
                        "heading": "Format",
                        "score": 0.82,
                        "snippet": "Six clubs enter the play-offs.",
                    }
                ],
                meta={},
            )
        return Envelope(data=[], meta={})

    def freshness(self) -> dict:
        return {
            "as_of": "2026-10-13T02:02:15Z",
            "competitions": [
                {
                    "code": "PL",
                    "name": "Premier League",
                    "status": "fresh",
                    "last_success_at": "2026-10-13T02:02:15Z",
                    "age_minutes": 12,
                },
                {
                    "code": "SA",
                    "name": "Serie A",
                    "status": "stale",
                    "last_success_at": "2026-10-10T02:02:15Z",
                    "age_minutes": 3000,
                },
            ],
        }


def _ctx() -> ToolContext:
    return ToolContext(FakeBackend())


def test_resolver_finds_a_club_nickname_and_its_competition() -> None:
    registry = _ctx().cache.get()
    spurs = registry.find_team("spurs table?")
    assert spurs is not None
    assert spurs.id == 73
    assert registry.team_competition(spurs.id).code == "PL"


def test_resolver_finds_a_competition_by_alias() -> None:
    registry = _ctx().cache.get()
    assert registry.find_competition("where are Napoli in Serie A?").code == "SA"


def test_standings_returns_the_focus_row() -> None:
    result = get_standings(_ctx(), "where are Arsenal in the table?")
    assert result["competition"]["code"] == "PL"
    assert result["focus"]["team"] == "Arsenal FC"
    assert result["data_as_of"] == "2026-10-13T02:02:15Z"


def test_fixtures_filters_to_upcoming_matches() -> None:
    result = get_fixtures(_ctx(), "Arsenal fixtures")
    assert [match["id"] for match in result["matches"]] == [2]


def test_match_result_picks_the_latest_finished_match() -> None:
    result = get_match_result(_ctx(), "did Arsenal win?")
    assert result["match"]["id"] == 1
    assert result["match"]["home_goals"] == 2


def test_form_returns_the_counted_summary() -> None:
    result = get_team_form(_ctx(), "how have Arsenal been playing?")
    assert result["summary"]["points"] == 12


def test_head_to_head_needs_two_teams() -> None:
    assert get_head_to_head(_ctx(), "who is better?")["error"] == "not_found"
    result = get_head_to_head(_ctx(), "Arsenal and Chelsea head to head")
    assert result["summary"]["played"] == 4


def test_knowledge_returns_a_citation_and_an_empty_result_is_real() -> None:
    hit = search_knowledge(_ctx(), "how does the playoff work")
    assert hit["hits"][0]["source_file"] == "formats/championship-playoffs.md"
    assert search_knowledge(_ctx(), "offside rule")["hits"] == []


def test_top_scorers_returns_the_snapshot_and_the_player() -> None:
    result = get_top_scorers(_ctx(), "who is the top scorer in the premier league?")
    assert result["competition"]["code"] == "PL"
    assert result["scorers"][0]["player"]["name"] == "Bukayo Saka"
    assert result["scorers"][0]["goals"] == 5
    assert result["data_as_of"] == "2026-10-22T00:00:00Z"


def test_a_scorer_question_without_a_competition_matches_the_player() -> None:
    result = get_top_scorers(_ctx(), "how many goals has Saka scored this season?")
    assert result["competition"]["code"] == "PL"
    assert result["scorers"][0]["player"]["name"] == "Bukayo Saka"
    assert result["data_as_of"] == "2026-10-22T00:00:00Z"


def test_an_unknown_scorer_question_asks_for_more() -> None:
    assert get_top_scorers(_ctx(), "who has scored the most?")["error"] == "not_found"


def test_freshness_can_be_filtered_to_one_competition() -> None:
    result = get_data_freshness(_ctx(), "how fresh is the premier league?")
    assert [row["code"] for row in result["competitions"]] == ["PL"]


def test_the_registry_is_cached_between_calls() -> None:
    ctx = _ctx()
    ctx.cache.get()
    first = ctx.backend.standings_calls
    ctx.cache.get()
    assert ctx.backend.standings_calls == first


def _client() -> TestClient:
    return TestClient(create_app(backend=FakeBackend(), token=TOKEN))


def _rpc(client: TestClient, payload: dict, *, token: str = TOKEN):
    return client.post("/mcp", json=payload, headers={"Authorization": f"Bearer {token}"})


def test_health_is_open_and_reports_the_tool_count() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json()["tools"] == 8


def test_mcp_requires_the_bearer_token() -> None:
    response = _client().post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401


def test_initialize_and_tools_list_are_protocol_shaped() -> None:
    client = _client()
    init = _rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).json()
    assert init["result"]["protocolVersion"] == "2024-11-05"
    assert init["result"]["serverInfo"]["name"] == "hermes-football-mcp"
    listing = _rpc(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()
    assert len(listing["result"]["tools"]) == 8
    assert {tool["name"] for tool in listing["result"]["tools"]} == {
        "get_standings",
        "get_fixtures",
        "get_match_result",
        "get_team_form",
        "get_head_to_head",
        "search_knowledge",
        "get_data_freshness",
        "get_top_scorers",
    }


def test_tools_call_returns_text_content() -> None:
    client = _client()
    response = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_standings", "arguments": {"query": "where are Arsenal?"}},
        },
    ).json()
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["focus"]["team"] == "Arsenal FC"
    assert response["result"]["isError"] is False


def test_an_unknown_tool_is_a_protocol_error() -> None:
    response = _rpc(
        _client(),
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "drop_tables", "arguments": {}}},
    ).json()
    assert response["error"]["code"] == -32602


def test_a_backend_failure_is_a_tool_error_not_a_crash() -> None:
    class Broken(FakeBackend):
        def search_knowledge(self, query: str, *, k: int = 3, min_score: float = 0.25):
            raise BackendError("backend is down", status=503)

    client = TestClient(create_app(backend=Broken(), token=TOKEN))
    response = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "search_knowledge", "arguments": {"query": "playoff"}},
        },
    ).json()
    assert response["result"]["isError"] is True
    assert "backend is down" in response["result"]["content"][0]["text"]


def test_a_notification_gets_202_with_no_body() -> None:
    response = _client().post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 202
