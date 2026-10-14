"""The endpoints that answer questions rather than list rows: head-to-head, a team and its form, the
knowledge search, the turn log and the ingestion ledger.

What they have in common is that the API computes something - a record, a form line, a ranked passage
- and the contract says the counting happens here rather than in the model (`R-F4.2`). So these tests
check arithmetic, not just shape.
"""

from __future__ import annotations

import pytest

from tests.api_helpers import (
    COMPETITION,
    GROUP_COMPETITION,
    MATCH_ID,
    OPPONENT,
    TEAM,
    THIRD,
)

# ------------------------------------------------------------------------------------------------
# /head-to-head
# ------------------------------------------------------------------------------------------------


def test_head_to_head_counts_the_meetings_itself(client, auth, seeded) -> None:
    body = client.get("/head-to-head", params={"teamA": TEAM, "teamB": OPPONENT}, headers=auth).json()
    assert body["data"]["teams"][0]["id"] == TEAM
    assert body["data"]["summary"] == {
        "played": 2,
        "team_a_wins": 1,
        "draws": 1,
        "team_b_wins": 0,
        "goals": {"team_a": 3, "team_b": 2},
    }
    assert [row["id"] for row in body["data"]["matches"]] == [MATCH_ID, 419840], "most recent first"
    assert body["data"]["window"] == {
        "matches_considered": 2,
        "from": "2025-03-10T15:00:00Z",
        "to": "2026-03-15T15:00:00Z",
    }


def test_head_to_head_summary_covers_the_window_while_matches_are_paged(client, auth, seeded) -> None:
    """`limit` must not change the answer to "who wins more often"."""
    limited = client.get("/head-to-head", params={"teamA": TEAM, "teamB": OPPONENT, "limit": 1}, headers=auth).json()
    assert len(limited["data"]["matches"]) == 1
    assert limited["data"]["summary"]["played"] == 2
    assert limited["data"]["window"]["matches_considered"] == 2


def test_head_to_head_can_be_scoped_to_a_competition(client, auth, seeded) -> None:
    scoped = client.get(
        "/head-to-head",
        params={"teamA": TEAM, "teamB": OPPONENT, "competition": "BL1"},
        headers=auth,
    ).json()
    assert scoped["data"]["summary"]["played"] == 0, "a window with no meetings is a count of zero"
    assert scoped["data"]["matches"] == []
    assert "from" not in scoped["data"]["window"], "an empty window has no dates to quote"


@pytest.mark.parametrize(
    ("params", "status", "code"),
    [
        ({"teamA": TEAM, "teamB": TEAM}, 400, "invalid_parameter"),
        ({"teamA": TEAM, "teamB": 999999}, 404, "not_found"),
        ({"teamA": 999999, "teamB": 888888}, 404, "not_found"),
    ],
)
def test_head_to_head_rejects_rubbish(client, auth, seeded, params, status, code) -> None:
    response = client.get("/head-to-head", params=params, headers=auth)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


# ------------------------------------------------------------------------------------------------
# /teams/{teamId} and /teams/{teamId}/form
# ------------------------------------------------------------------------------------------------


def test_team_detail_reports_whether_a_squad_is_actually_stored(client, auth, seeded) -> None:
    with_squad = client.get(f"/teams/{TEAM}", headers=auth).json()["data"]
    assert with_squad["name"] == "Arsenal FC"
    assert with_squad["founded"] == 1886
    assert with_squad["venue"] == "Emirates Stadium"
    assert with_squad["squad_available"] is True
    assert with_squad["squad_size"] == 3
    assert [row["code"] for row in with_squad["competitions"]] == ["CL", COMPETITION]

    without = client.get(f"/teams/{THIRD}", headers=auth).json()["data"]
    assert without["squad_available"] is False
    assert without["squad_size"] == 0
    assert "crest" not in without, "a null crest is left out"


def test_an_unknown_team_is_a_404(client, auth, seeded) -> None:
    response = client.get("/teams/999999", headers=auth)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_form_counts_wins_draws_losses_points_and_goals(client, auth, seeded) -> None:
    """Arsenal's four settled matches: 2-1 W, 3-1 L (away), 4-2 W and 1-1 D (away)."""
    body = client.get(f"/teams/{TEAM}/form", headers=auth).json()
    form = body["data"]
    assert form["summary"] == {
        "played": 4,
        "won": 2,
        "drawn": 1,
        "lost": 1,
        "points": 7,
        "goals_for": 8,
        "goals_against": 7,
        "clean_sheets": 0,
    }
    assert form["window"] == {
        "matches_considered": 4,
        "from": "2025-03-10T15:00:00Z",
        "to": "2026-05-05T15:00:00Z",
    }
    # Newest first, and `home` is what says which end the scoreline is read from.
    assert [row["match_id"] for row in form["matches"]] == [419826, 419825, MATCH_ID, 419840]
    assert [row["result"] for row in form["matches"]] == ["W", "L", "W", "D"]
    away_loss = form["matches"][1]
    assert away_loss["home"] is False
    assert away_loss["score"] == {"home": 3, "away": 1}, "the scoreline as published, not rotated"
    assert away_loss["opponent"]["id"] == THIRD
    assert away_loss["competition"] == "Premier League"


def test_form_honours_last_and_the_competition_filter(client, auth, seeded) -> None:
    shortest = client.get(f"/teams/{TEAM}/form", params={"last": 1}, headers=auth).json()["data"]
    assert [row["match_id"] for row in shortest["matches"]] == [419826]
    assert shortest["summary"]["played"] == 1
    assert shortest["window"]["matches_considered"] == 1

    other = client.get(f"/teams/{TEAM}/form", params={"competition": GROUP_COMPETITION}, headers=auth).json()[
        "data"
    ]
    assert other["summary"]["played"] == 0
    assert other["matches"] == []


def test_form_is_computed_from_settled_matches_only(client, auth, seeded) -> None:
    """Arsenal have a scheduled fixture in the seed; it must not enter the form line, and a form
    window narrower than the whole history must not invent a result for it."""
    form = client.get(f"/teams/{TEAM}/form", params={"last": 20}, headers=auth).json()["data"]
    assert 419830 not in [row["match_id"] for row in form["matches"]]
    assert form["summary"]["played"] == 4


def test_form_for_an_unknown_team_is_a_404(client, auth, seeded) -> None:
    assert client.get("/teams/999999/form", headers=auth).status_code == 404


# ------------------------------------------------------------------------------------------------
# /search/knowledge
# ------------------------------------------------------------------------------------------------


def test_knowledge_search_returns_the_passage_with_its_file_and_heading(client, auth, seeded) -> None:
    response = client.get(
        "/search/knowledge", params={"q": "how long are scores delayed", "minScore": 0}, headers=auth
    )
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "how long are scores delayed"
    hits = body["data"]
    assert hits, "the seeded corpus is searchable"
    assert hits[0]["source_file"] == "policy/free-tier-delay-and-coverage.md", "a citable path in the corpus"
    assert hits[0]["heading"]
    assert hits[0]["snippet"]
    assert 0 <= hits[0]["score"] <= 1
    # A knowledge answer is our own writing: local source, and no provider timestamp to quote.
    assert body["meta"]["source"] == "hermes-football"
    assert body["meta"]["data_as_of"] is None


def test_the_score_threshold_drops_hits_rather_than_padding_them(client, auth, seeded) -> None:
    """The contract's words: "hits below it are dropped rather than padded". With the deterministic
    test embedder unrelated vectors score low, which is exactly the case the threshold exists for."""
    everything = client.get("/search/knowledge", params={"q": "offside rule", "minScore": 0}, headers=auth).json()
    assert everything["data"]
    best = max(hit["score"] for hit in everything["data"])

    threshold = min(1.0, best + 0.01)
    nothing = client.get(
        "/search/knowledge", params={"q": "offside rule", "minScore": threshold}, headers=auth
    ).json()
    assert nothing["data"] == [], "a query with no passage above the threshold is an empty answer"


def test_knowledge_search_respects_k(client, auth, seeded) -> None:
    body = client.get("/search/knowledge", params={"q": "free tier", "k": 1, "minScore": 0}, headers=auth).json()
    assert len(body["data"]) == 1
    assert len(seeded.chunks) >= 2, "the fixture has more than one passage to cut down to one"


def test_knowledge_search_returns_snippets_that_fit_in_a_prompt(client, auth, seeded) -> None:
    from backend.schemas import SNIPPET_MAX_LENGTH

    body = client.get("/search/knowledge", params={"q": "free tier", "minScore": 0}, headers=auth).json()
    assert all(len(hit["snippet"]) <= SNIPPET_MAX_LENGTH for hit in body["data"])


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({"q": "x"}, 400),
        ({"q": "free tier", "k": 11}, 400),
        ({"q": "free tier", "minScore": 2}, 400),
        ({"q": "free tier", "competition": "XX"}, 400),
        ({}, 400),
    ],
)
def test_knowledge_search_validates_its_parameters(client, auth, seeded, params, status) -> None:
    assert client.get("/search/knowledge", params=params, headers=auth).status_code == status


def test_a_competition_tag_on_a_note_boosts_it_without_gating_it(session, tmp_path, settings, embedder, auth) -> None:
    """`competition` "boosts passages tagged with this competition". The tag lives in the manifest, not
    on the chunk row, so the boost is checked against the manifest: the same passage, the same query,
    and a score that moves by exactly `COMPETITION_BOOST` for the competition it is tagged with and
    does not move for any other. Tested here rather than through the shipped corpus because no note
    carries a competition tag yet - M4 writes them, and inventing one would be a fiction.
    """
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from backend.app import create_app
    from backend.services.knowledge import COMPETITION_BOOST
    from backend.settings import BackendSettings
    from db.models import KnowledgeChunk, new_id
    from db.session import create_db_engine

    corpus = tmp_path / "agent-knowledge"
    (corpus / "policy").mkdir(parents=True)
    (corpus / "policy" / "premier-league.md").write_text("# Premier League\n\nTwenty teams, 38 games.\n")
    (corpus / "manifest.yaml").write_text(
        "version: 1\nnotes:\n"
        "  - file: policy/premier-league.md\n"
        "    title: Premier League format\n"
        "    question_classes: [formats]\n"
        "    competitions: [PL]\n"
        '    source: "test fixture"\n'
        "    owner: Ahmad Ammari\n"
        "    status: draft\n"
        "    reviewed_at: 2026-10-10\n"
    )

    text = "Twenty teams play thirty-eight games in the Premier League."
    [vector] = embedder.embed_documents([text], titles=["Premier League"])
    session.add(
        KnowledgeChunk(
            id=new_id(),
            source_file="policy/premier-league.md",
            heading="Premier League format",
            ordinal=0,
            chunk_text=text,
            embedding=vector,
            embedding_model=embedder.model,
            embedding_dim=embedder.dim,
            content_hash="b" * 64,
        )
    )
    session.commit()

    tagged = replace(settings, knowledge_dir=corpus)
    engine = create_db_engine(tagged)
    try:
        app = create_app(
            BackendSettings(db=tagged, agent_token="test-agent-token"), engine=engine, embedder=embedder
        )
        with TestClient(app) as client:
            def search(competition: str | None) -> list[dict]:
                params = {"q": "how many teams are in the premier league", "minScore": 0}
                if competition:
                    params["competition"] = competition
                response = client.get("/search/knowledge", params=params, headers=auth)
                assert response.status_code == 200, response.text
                return response.json()["data"]

            plain = search(None)
            boosted = search("PL")
            unrelated = search("BL1")
    finally:
        engine.dispose()

    assert [hit["source_file"] for hit in plain] == ["policy/premier-league.md"]
    assert boosted[0]["score"] == pytest.approx(plain[0]["score"] + COMPETITION_BOOST)
    assert unrelated[0]["score"] == pytest.approx(plain[0]["score"]), "a tag is not a wildcard"


# ------------------------------------------------------------------------------------------------
# /agent/turns
# ------------------------------------------------------------------------------------------------


def test_agent_turns_serve_the_route_a_turn_took(client, auth, seeded) -> None:
    """Rule 10: `route`, `route_source` and `route_confidence` are why these three fields joined the
    contract in v0.2.0."""
    body = client.get("/agent/turns", headers=auth).json()
    assert body["pagination"]["total"] == 3
    newest = body["data"][0]
    assert newest["route"] == "refuse"
    assert newest["route_source"] == "model"
    assert newest["route_confidence"] == 0.62
    assert newest["grounded"] is False
    assert newest["review_status"] == "flagged"
    assert newest["review_note"]
    assert newest["model"] == "hermes-3-405b"

    routed_to_tool = next(row for row in body["data"] if row["route"] == "tool")
    assert routed_to_tool["route_source"] == "rules"
    assert "route_confidence" not in routed_to_tool, "deterministic routing has no confidence to report"
    assert routed_to_tool["data_as_of"] == "2026-10-11T12:43:00Z"
    assert routed_to_tool["tool_calls"] == [
        {
            "name": "get_standings",
            "status": "ok",
            "args_summary": {"competition": COMPETITION},
            "latency_ms": 12,
            "policy_decision": "allowlisted",
        }
    ]


def test_a_tool_call_that_cannot_be_described_is_dropped_not_invented(client, auth, seeded) -> None:
    """One of the seeded calls has a name and nothing else. `ToolCall` requires a status, so the call
    is left out while its turn still serves."""
    turn = next(row for row in client.get("/agent/turns", headers=auth).json()["data"] if row["route"] == "knowledge")
    assert [call["name"] for call in turn["tool_calls"]] == ["search_knowledge"]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"grounded": True}, 2),
        ({"grounded": False}, 1),
        ({"reviewStatus": "flagged"}, 1),
        ({"reviewStatus": "correct"}, 1),
        ({"reviewStatus": "wrong"}, 0),
    ],
)
def test_turn_filters(client, auth, seeded, params, expected) -> None:
    body = client.get("/agent/turns", params=params, headers=auth).json()
    assert body["pagination"]["total"] == expected


def test_turns_can_be_read_since_a_moment(client, auth, seeded) -> None:
    from datetime import timedelta

    # The knowledge turn is exactly an hour old and the refusal is 45 minutes old, so a 50-minute
    # window isolates the latest one without sitting on the boundary.
    since = (seeded.now - timedelta(minutes=50)).isoformat()
    body = client.get("/agent/turns", params={"since": since}, headers=auth).json()
    assert body["pagination"]["total"] == 1, "only the turn from 45 minutes ago"
    assert body["data"][0]["route"] == "refuse"

    naive = (seeded.now - timedelta(minutes=50)).replace(tzinfo=None).isoformat()
    assert client.get("/agent/turns", params={"since": naive}, headers=auth).json()["pagination"]["total"] == 1, (
        "a client that omits the offset is not silently given every turn"
    )


def test_a_turn_log_is_ordered_newest_first_and_pages(client, auth, seeded) -> None:
    body = client.get("/agent/turns", params={"limit": 2}, headers=auth).json()
    assert len(body["data"]) == 2
    assert body["pagination"] == {"limit": 2, "offset": 0, "total": 3, "has_more": True}
    assert body["data"][0]["created_at"] > body["data"][1]["created_at"]
    assert body["meta"]["source"] == "hermes-football"


# ------------------------------------------------------------------------------------------------
# /meta/ingest-runs
# ------------------------------------------------------------------------------------------------


def test_ingest_runs_describe_each_run_and_its_failures(client, auth, seeded) -> None:
    body = client.get("/meta/ingest-runs", headers=auth).json()
    assert body["pagination"]["total"] == 5
    assert [row["status"] for row in body["data"]] == ["failed", "succeeded", "partial", "succeeded", "succeeded"]

    partial = next(row for row in body["data"] if row["status"] == "partial")
    assert partial["trigger"] == "schedule"
    assert partial["competitions"] == [COMPETITION, "EC"]
    assert partial["errors"] == [
        {
            "resource": "standings:EC",
            "competition": "EC",
            "message": "upstream returned HTTP 404 (resource not found) for /competitions/EC/standings",
        },
        {
            "resource": "matches:2024-06-14..2024-09-11",
            "message": "upstream returned HTTP 400 for /matches",
        },
    ], "a ledger `resource` that is not a competition keeps its own name and claims none"
    assert partial["calls_used"] == 54
    assert partial["rows"] == {"inserted": 100, "updated": 2, "unchanged": 0}
    assert partial["duration_seconds"] == 300.5

    measurement = next(row for row in body["data"] if row["competitions"] == [])
    assert measurement["calls_used"] == 10, "the score-delay poll: one call, no competition scope"


def test_ingest_runs_can_be_filtered_by_status(client, auth, seeded) -> None:
    failed = client.get("/meta/ingest-runs", params={"status": "failed"}, headers=auth).json()
    assert failed["pagination"]["total"] == 1
    assert all(row["status"] == "failed" for row in failed["data"])
    assert client.get("/meta/ingest-runs", params={"status": "nonsense"}, headers=auth).status_code == 400


def test_the_ledger_is_the_only_thing_that_knows_when_we_last_ran(client, auth, seeded) -> None:
    """No request path may reach upstream, so the newest `finished_at` is the honest answer to "when
    did this deployment last talk to the provider"."""
    body = client.get("/meta/ingest-runs", headers=auth).json()
    finished = [row["finished_at"] for row in body["data"] if row["finished_at"]]
    assert max(finished) > min(finished)
