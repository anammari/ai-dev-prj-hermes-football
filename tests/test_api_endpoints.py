"""The data endpoints, read as a client would: exact rows, exact filters, exact errors.

The contract tests prove the *shape* of every response. These prove the *content*: that the default
season is the current one, that a snapshot query returns the table as it stood on that date, that a
fixture has no score, and that a competition with nothing ingested says so in the way the contract
prescribes ("no data", never "no matches").
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import backend
from backend.app import create_app
from backend.settings import BackendSettings
from db.session import create_db_engine
from ingest.knowledge.embedding import FakeEmbedder
from tests import api_helpers
from tests.api_helpers import COMPETITION, GROUP_COMPETITION, MATCH_ID, NEVER_INGESTED, OPPONENT, SEASON, TEAM, THIRD

# ------------------------------------------------------------------------------------------------
# /health and the served contract
# ------------------------------------------------------------------------------------------------


def test_health_reports_the_running_version_and_the_schema_revision(client: TestClient, auth) -> None:
    response = client.get("/health")
    assert response.status_code == 200, "the liveness probe must not need a token"
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == backend.__version__
    assert body["db"] == {"status": "ok", "schema_revision": "0003_agent_turn_writer"}
    assert isinstance(body["uptime_seconds"], int)


def test_health_degrades_instead_of_failing_when_the_database_is_gone(tmp_path, settings) -> None:
    """A liveness probe that answers 500 on a database blip restarts the container for no reason; it
    reports the database's state instead, and stays a 200."""
    unreachable = replace(settings, database_url=f"sqlite+pysqlite:///{tmp_path / 'empty.db'}")
    engine = create_db_engine(unreachable)
    try:
        app = create_app(
            BackendSettings(db=unreachable, agent_token="test-agent-token"),
            engine=engine,
            embedder=FakeEmbedder(),
        )
        with TestClient(app) as client:
            body = client.get("/health").json()
        assert body["status"] == "degraded"
        assert body["db"]["status"] == "error"
        assert body["db"]["schema_revision"] == "unknown"
    finally:
        engine.dispose()


def test_swagger_ui_renders_from_the_served_file(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'url: "/openapi.yaml"' in response.text or "'/openapi.yaml'" in response.text


# ------------------------------------------------------------------------------------------------
# /competitions
# ------------------------------------------------------------------------------------------------


def test_competitions_lists_what_has_been_ingested_with_its_coverage(client: TestClient, auth, seeded) -> None:
    response = client.get("/competitions", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert [row["code"] for row in body["data"]] == ["BL1", "CL", "PL", "SA", "WC"], "reproducible order"

    premier = next(row for row in body["data"] if row["code"] == COMPETITION)
    assert premier["name"] == "Premier League"
    assert premier["area"] == "England"
    assert premier["current_season"] == SEASON
    assert premier["season_start"] == "2026-08-14"
    assert premier["coverage"] == {
        "fixtures": True,
        "standings": True,
        "scorers": True,
        "lineups": False,
        "live_scores": False,
        "note": "Live scores, odds, lineups and advanced statistics are paid tiers",
    }

    bundesliga = next(row for row in body["data"] if row["code"] == "BL1")
    assert "note" not in bundesliga["coverage"], "a null note is left out, not sent as null"
    assert "season_start" not in bundesliga, "and so is a season the provider has not published"

    # `data_as_of` is the provider's newest stamp, and the contract's `source` names the provider.
    assert body["meta"]["data_as_of"] == "2026-10-11T12:45:00Z"
    assert body["meta"]["source"] == "football-data.org"
    assert body["meta"]["upstream_delay_minutes"] is None
    assert "pagination" not in body, "/competitions is not a paginated list in the contract"


# ------------------------------------------------------------------------------------------------
# /competitions/{code}/standings
# ------------------------------------------------------------------------------------------------


def test_standings_returns_the_newest_table_of_the_current_season(client: TestClient, auth, seeded) -> None:
    response = client.get(f"/competitions/{COMPETITION}/standings", headers=auth)
    assert response.status_code == 200
    table = response.json()["data"]
    assert table["competition"] == {"code": COMPETITION, "name": "Premier League"}
    assert table["season"] == SEASON
    assert table["type"] == "TOTAL", "the HOME and AWAY splits are stored but never served"
    assert table["stage"] == "REGULAR_SEASON"
    assert [row["position"] for row in table["table"]] == [1, 2, 3]
    assert [row["team"]["id"] for row in table["table"]] == [TEAM, OPPONENT, THIRD]
    assert [row["points"] for row in table["table"]] == [25, 24, 23], "the newest snapshot, not the older one"
    assert table["table"][0]["form"] == "WWDWW"


def test_standings_as_of_a_snapshot_returns_the_older_table(client: TestClient, auth, seeded) -> None:
    """A point-in-time table is the whole reason `snapshot` exists: "as it stood on that date"."""
    response = client.get(
        f"/competitions/{COMPETITION}/standings", params={"snapshot": "2026-10-31"}, headers=auth
    )
    assert response.status_code == 200
    table = response.json()["data"]
    assert table["updated_at"] < "2026-11-01", "the older snapshot was written before the newer one"
    assert [row["points"] for row in table["table"]] == [19, 18, 17]
    assert table["table"][0]["played"] == 10


def test_standings_echoes_a_group_label_only_when_every_row_agrees(client: TestClient, auth, seeded) -> None:
    grouped = client.get(f"/competitions/{GROUP_COMPETITION}/standings", headers=auth).json()["data"]
    assert grouped["group"] == "GROUP_A"
    assert grouped["stage"] == "LEAGUE_STAGE"
    assert "group" not in client.get(f"/competitions/{COMPETITION}/standings", headers=auth).json()["data"]


def test_standings_data_as_of_is_the_snapshot_write_time(client: TestClient, auth, seeded) -> None:
    body = client.get(f"/competitions/{COMPETITION}/standings", headers=auth).json()
    assert body["meta"]["data_as_of"] == body["data"]["updated_at"], (
        "a standings table has no provider stamp of its own, so it quotes when we wrote it"
    )


@pytest.mark.parametrize(
    ("params", "status", "code"),
    [
        ({"season": 1999}, 404, "not_found"),
        ({"snapshot": "2026-01-01"}, 404, "not_found"),
        ({"matchday": 7}, 404, "not_found"),
        ({"season": 2026, "snapshot": "2026-11-01", "matchday": 3}, 404, "not_found"),
    ],
)
def test_standings_404s_are_about_a_missing_resource(client, auth, seeded, params, status, code) -> None:
    """The competition and season exist; the season, snapshot or matchday asked for does not."""
    response = client.get(f"/competitions/{COMPETITION}/standings", params=params, headers=auth)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_standings_for_a_competition_with_no_table_says_no_data_not_not_found(client, auth, seeded) -> None:
    """The contract is explicit: `UpstreamUnavailable` is "not in the database *yet*" and its example
    message is this one. A 404 would read as "wrong competition"; a 503 reads as "we have nothing"."""
    response = client.get(f"/competitions/{NEVER_INGESTED}/standings", headers=auth)
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "data_not_available"
    assert error["message"] == f"No standings have been ingested for {NEVER_INGESTED} yet."


def test_an_unknown_competition_code_is_a_400_not_a_404(client: TestClient, auth, seeded) -> None:
    response = client.get("/competitions/XX/standings", headers=auth)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_parameter"
    assert "XX" in response.json()["error"]["details"]["value"]


# ------------------------------------------------------------------------------------------------
# /competitions/{code}/matches
# ------------------------------------------------------------------------------------------------


def test_matches_default_to_the_current_season_and_are_ordered_by_kickoff(client, auth, seeded) -> None:
    response = client.get(f"/competitions/{COMPETITION}/matches", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body["data"]] == [MATCH_ID, 419824, 419825, 419826, 419830]
    assert body["pagination"] == {"limit": 50, "offset": 0, "total": 5, "has_more": False}
    assert body["meta"]["data_as_of"] == "2026-10-11T12:43:00Z", "the newest provider stamp on this page"


@pytest.mark.parametrize(
    ("params", "ids"),
    [
        ({"season": 2025}, [419840]),
        ({"season": 2026, "matchday": 5}, [MATCH_ID]),
        ({"season": 2026, "status": "SCHEDULED"}, [419830]),
        ({"season": 2026, "teamId": TEAM}, [MATCH_ID, 419825, 419826, 419830]),
        ({"season": 2026, "dateFrom": "2026-04-01", "dateTo": "2026-04-30"}, [419824, 419825]),
        ({"season": 2026, "teamId": THIRD, "status": "FINISHED"}, [419824, 419825, 419826]),
    ],
)
def test_match_filters_compose(client, auth, seeded, params, ids) -> None:
    body = client.get(f"/competitions/{COMPETITION}/matches", params=params, headers=auth).json()
    assert [row["id"] for row in body["data"]] == ids
    assert body["pagination"]["total"] == len(ids)


def test_a_filter_that_matches_nothing_is_an_empty_page_not_an_error(client, auth, seeded) -> None:
    """A competition that has data, asked for a window with none: that is an answer."""
    body = client.get(
        f"/competitions/{COMPETITION}/matches",
        params={"season": 2026, "dateFrom": "2027-01-01"},
        headers=auth,
    ).json()
    assert body["data"] == []
    assert body["pagination"]["total"] == 0


def test_matches_for_a_competition_never_ingested_says_no_data(client, auth, seeded) -> None:
    """`openapi.yaml`: "Clients must report this as 'no data', never as 'no matches'"."""
    response = client.get(f"/competitions/{NEVER_INGESTED}/matches", headers=auth)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "data_not_available"


def test_pagination_is_reported_and_has_more_is_derived(client, auth, seeded) -> None:
    first = client.get(f"/competitions/{COMPETITION}/matches", params={"limit": 2}, headers=auth).json()
    assert first["pagination"] == {"limit": 2, "offset": 0, "total": 5, "has_more": True}
    last = client.get(
        f"/competitions/{COMPETITION}/matches", params={"limit": 2, "offset": 4}, headers=auth
    ).json()
    assert [row["id"] for row in last["data"]] == [419830]
    assert last["pagination"] == {"limit": 2, "offset": 4, "total": 5, "has_more": False}


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"season": 1800}, {"matchday": 0}])
def test_out_of_range_parameters_are_a_400_with_the_contract_error_shape(client, auth, seeded, params) -> None:
    response = client.get(f"/competitions/{COMPETITION}/matches", params=params, headers=auth)
    assert response.status_code == 400, params
    assert response.json()["error"]["code"] == "invalid_parameter"


# ------------------------------------------------------------------------------------------------
# /matches/{matchId}
# ------------------------------------------------------------------------------------------------


def test_a_finished_match_carries_its_score_and_its_provider_stamp(client, auth, seeded) -> None:
    body = client.get(f"/matches/{MATCH_ID}", headers=auth).json()
    match = body["data"]
    assert match["status"] == "FINISHED"
    assert match["home_team"]["id"] == TEAM
    assert match["away_team"]["id"] == OPPONENT
    assert match["score"] == {
        "winner": "HOME_TEAM",
        "duration": "REGULAR",
        "full_time": {"home": 2, "away": 1},
        "half_time": {"home": 1, "away": 0},
    }
    assert match["referees"][0]["name"] == "Michael Oliver"
    # The provider's stamp, not when we wrote the row: rule 2 quotes this number to a user.
    assert match["last_updated"] == "2026-10-11T12:40:00Z"
    assert body["meta"]["data_as_of"] == match["last_updated"]


def test_a_fixture_has_no_score_and_no_stamp_rather_than_zeroes(client, auth, seeded) -> None:
    """0-0 is a result. A scheduled match that reports one is the worst kind of wrong answer."""
    body = client.get("/matches/419830", headers=auth).json()
    match = body["data"]
    assert match["status"] == "SCHEDULED"
    assert "score" not in match
    assert "last_updated" not in match
    assert body["meta"]["data_as_of"] is None


def test_a_match_that_is_not_stored_is_a_404(client, auth, seeded) -> None:
    response = client.get("/matches/999999", headers=auth)
    assert response.status_code == 404
    assert response.json()["error"]["details"] == {"match": 999999}


def test_a_match_id_must_be_an_integer(client, auth, seeded) -> None:
    assert client.get("/matches/not-an-id", headers=auth).status_code == 400


def test_two_matches_returned_by_different_endpoints_agree(client, auth, seeded) -> None:
    """One serialiser, so a match cannot differ between the list, the detail and head-to-head."""
    listed = client.get(f"/competitions/{COMPETITION}/matches", params={"matchday": 5}, headers=auth).json()[
        "data"
    ][0]
    detail = client.get(f"/matches/{MATCH_ID}", headers=auth).json()["data"]
    head_to_head = client.get(
        "/head-to-head", params={"teamA": TEAM, "teamB": OPPONENT}, headers=auth
    ).json()["data"]["matches"][0]
    assert listed == detail == head_to_head


def test_the_seed_is_what_the_contract_examples_describe(session: Session, seeded) -> None:
    """Guards the sweep in `test_api_contract.py`: its requests come from the contract's examples, so
    those examples have to keep resolving to rows in this fixture."""

    def example(operation_id: str, name: str):
        for spec in api_helpers.parameters(operation_id):
            if spec["name"] == name:
                return api_helpers.resolve(spec.get("schema", {}))["example"]
        raise AssertionError(f"{operation_id} has no {name}")

    assert seeded.runs and seeded.turns and seeded.chunks
    assert example("getMatch", "matchId") == MATCH_ID
    assert example("getTeam", "teamId") == TEAM
    assert example("getStandings", "season") == SEASON
    code = next(spec for spec in api_helpers.parameters("getStandings") if spec["name"] == "code")
    assert api_helpers.resolve(code["schema"])["enum"][0] == COMPETITION

def test_the_app_closes_only_the_embedder_it_created(engine, backend_settings, monkeypatch) -> None:
    """Ownership of an injected resource.

    The stack suite shares one module-scoped `OllamaEmbedder` across several apps; an app that closed
    it on shutdown left every later embedding call raising "Cannot send a request, as the client has
    been closed", which surfaced as a 500 on one operation of the contract sweep and nowhere else.
    The unit suite could not see it, because the deterministic embedder has no `close` to call.
    """

    class Watched(FakeEmbedder):
        closed = False

        def close(self) -> None:
            self.closed = True

    injected = Watched()
    with TestClient(create_app(backend_settings, engine=engine, embedder=injected)):
        pass
    assert injected.closed is False, "the app closed an embedder it did not build"

    built = Watched()
    monkeypatch.setattr("backend.app.OllamaEmbedder", lambda **_kwargs: built)
    with TestClient(create_app(backend_settings, engine=engine)):
        pass
    assert built.closed is True, "the app leaked the embedder it built itself"


def test_top_scorers_returns_the_latest_snapshot_in_order(client: TestClient, auth, seeded) -> None:
    response = client.get("/competitions/PL/top-scorers", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["competition"]["code"] == "PL"
    assert body["data"]["season"] == 2026
    assert body["data"]["snapshot"] == "2026-11-01", "the newest stored snapshot, not the older one"
    scorers = body["data"]["scorers"]
    assert [row["player"]["name"] for row in scorers] == ["Bukayo Saka", "Declan Rice"]
    assert scorers[0]["goals"] == 5
    assert scorers[0]["team"]["name"] == "Arsenal FC"
    assert body["meta"]["data_as_of"].startswith(body["data"]["snapshot"])


def test_top_scorers_snapshot_returns_the_table_as_it_stood(client: TestClient, auth, seeded) -> None:
    """`snapshot` is the point-in-time question, and the contract's own example date is what the
    sweep sends: with fixed fixtures it must select the older table instead of depending on the clock."""
    body = client.get("/competitions/PL/top-scorers", params={"snapshot": "2026-10-22"}, headers=auth).json()
    assert body["data"]["snapshot"] == "2026-10-12"
    assert [row["goals"] for row in body["data"]["scorers"]] == [4, 2]
