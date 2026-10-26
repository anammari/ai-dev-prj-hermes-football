"""`/evals/runs`: the scoreboard reads back what the harness stored.

The contract tests prove the shape; these prove the content a reader acts on: the run a dashboard
draws first, the per-question results behind a macro-F1 delta, the filters, and the two errors a
client must be able to tell apart (an unknown run is `404`, a malformed id is `400`).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api_helpers import EVAL_RUN_ID

# ------------------------------------------------------------------------------------------------
# The list
# ------------------------------------------------------------------------------------------------


def test_the_list_serves_the_newest_run_first(client: TestClient, auth: dict[str, str], seeded) -> None:
    body = client.get("/evals/runs", headers=auth).json()
    assert body["pagination"]["total"] == 1
    assert len(body["data"]) == 1
    run = body["data"][0]
    assert run["id"] == EVAL_RUN_ID
    assert run["set_name"] == "golden-2026-10-26"
    assert run["source"] == "live"
    assert run["status"] == "succeeded"
    assert run["passed"] is False, "the seeded run failed its gate; a failed run stays visible"
    assert run["failure_reasons"] == ["retrieval recall 0.90 is below the 0.92 floor"]
    assert run["metrics"]["routing"]["macro_f1"] == 0.94
    assert body["meta"]["source"] == "hermes-football"


def test_the_list_filters_by_set_name_and_outcome(client: TestClient, auth: dict[str, str], seeded) -> None:
    same_set = client.get("/evals/runs", params={"setName": "golden-2026-10-26"}, headers=auth).json()
    assert same_set["pagination"]["total"] == 1
    assert client.get("/evals/runs", params={"setName": "another-set"}, headers=auth).json()["data"] == []
    passed = client.get("/evals/runs", params={"passed": "true"}, headers=auth).json()
    assert passed["data"] == [], "the seeded run did not pass"
    failed = client.get("/evals/runs", params={"passed": "false"}, headers=auth).json()
    assert failed["pagination"]["total"] == 1


def test_the_list_honours_limit_and_offset(client: TestClient, auth: dict[str, str], seeded) -> None:
    page = client.get("/evals/runs", params={"limit": 1, "offset": 1}, headers=auth).json()
    assert page["data"] == []
    assert page["pagination"] == {"limit": 1, "offset": 1, "total": 1, "has_more": False}


# ------------------------------------------------------------------------------------------------
# The detail
# ------------------------------------------------------------------------------------------------


def test_the_detail_serves_the_run_and_every_result(client: TestClient, auth: dict[str, str], seeded) -> None:
    body = client.get(f"/evals/runs/{EVAL_RUN_ID}", headers=auth).json()
    assert body["data"]["run"]["id"] == EVAL_RUN_ID
    results = body["data"]["results"]
    assert [result["question_id"] for result in results] == [
        "g-knowledge-tiebreakers-1",
        "g-tool-standings-1",
    ], "ordered by question id, so two runs are diffable line by line"

    routing_miss = results[0]
    assert routing_miss["expected_route"] == "knowledge"
    assert routing_miss["route"] == "tool", "the miss the run exists to make visible"
    assert routing_miss["scores"]["routing_correct"] is False
    assert routing_miss["retrieved"][0]["source_file"] == "tiebreakers/premier-league-goal-difference.md"

    correct = results[1]
    assert correct["scores"]["routing_correct"] is True
    assert correct["expected_tool"] == "get_standings"


def test_the_run_detail_quotes_the_run_that_produced_it(client: TestClient, auth: dict[str, str], seeded) -> None:
    body = client.get(f"/evals/runs/{EVAL_RUN_ID}", headers=auth).json()
    assert body["meta"]["data_as_of"] == body["data"]["run"]["finished_at"]
    assert body["meta"]["generated_at"] >= body["meta"]["data_as_of"]


# ------------------------------------------------------------------------------------------------
# The two errors
# ------------------------------------------------------------------------------------------------


def test_an_unknown_run_is_a_404_with_the_contract_shape(client: TestClient, auth: dict[str, str]) -> None:
    response = client.get("/evals/runs/00000000-0000-0000-0000-000000000000", headers=auth)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["request_id"]


def test_a_malformed_run_id_is_a_400_not_a_404(client: TestClient, auth: dict[str, str]) -> None:
    """The contract says `format: uuid`; a string that is not one is a bad parameter, and a client
    should not read it as "that run does not exist"."""
    response = client.get("/evals/runs/not-a-uuid", headers=auth)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_parameter"


def test_the_scoreboard_needs_a_token(client: TestClient) -> None:
    assert client.get("/evals/runs").status_code == 401
    assert client.get(f"/evals/runs/{EVAL_RUN_ID}").status_code == 401
