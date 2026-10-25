"""DB rows in, exactly what `openapi.yaml` describes out.

Every contract *value object* is assembled here and nowhere else, so a renamed field is a one-line
change in one file. The computed objects (team form, head-to-head, the freshness report) are built by
the service that computes them, out of these pieces.

The rule that matters here: **`pruned()` drops unknown values**, because `null` is not a legal
integer, array, or enum member in this contract. A fixture with no score must omit `duration` rather
than send `"duration": null`; a run with no row counts must omit `rows` rather than send nulls inside
it. `tests/test_api_contract.py` validates every response against the contract and is what keeps this
honest - it caught exactly this class of mistake while M3 was being written.
"""

from __future__ import annotations

import re
from typing import Any

from backend.meta import as_utc
from db.models import (
    AgentTurn,
    Competition,
    EvalResult,
    EvalRun,
    IngestRun,
    KnowledgeChunk,
    Match,
    Player,
    Standing,
    Team,
    TopScorer,
)

#: The longest passage the contract allows in a knowledge snippet.
SNIPPET_MAX_LENGTH = 1200

#: `ingest_runs.errors` records a failing `resource` such as `standings:EC` (see the M2 ledger). The
#: contract's error row wants a `competition` when one can be named; a date-window failure such as
#: `matches:2024-06-14..2024-09-11` covers several competitions and simply has none.
_COMPETITION_RESOURCE = re.compile(r"^(?:standings|scorers|teams):([A-Za-z0-9]{2,8})$")


def pruned(**values: Any) -> dict[str, Any]:
    """Only the keys we actually know something about."""
    return {key: value for key, value in values.items() if value is not None}


# ---------------------------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------------------------


def team_summary(team: Team) -> dict[str, Any]:
    return pruned(id=team.id, name=team.name, tla=team.tla, crest=team.crest)


def team_detail(team: Team, *, competitions: list[Competition], squad_size: int) -> dict[str, Any]:
    return {
        **team_summary(team),
        **pruned(area=team.area, founded=team.founded, venue=team.venue, club_colors=team.club_colors),
        "competitions": [{"code": row.code, "name": row.name} for row in competitions],
        # `squad_available` is computed, never stored (`_docs/data-model.md`): squads ARE on the free
        # tier, so false means ingestion has not stored one yet, which is a different statement from
        # "the plan forbids it" and the contract says the agent must not answer player questions when
        # it is false.
        "squad_available": squad_size > 0,
        "squad_size": squad_size,
    }


def competition(row: Competition) -> dict[str, Any]:
    return {
        "code": row.code,
        "name": row.name,
        **pruned(
            area=row.area,
            type=row.type,
            current_season=row.current_season,
            season_start=row.season_start.isoformat() if row.season_start else None,
            season_end=row.season_end.isoformat() if row.season_end else None,
        ),
        "coverage": {
            "fixtures": bool(row.coverage_fixtures),
            "standings": bool(row.coverage_standings),
            "scorers": bool(row.coverage_scorers),
            "lineups": bool(row.coverage_lineups),
            "live_scores": bool(row.coverage_live_scores),
            **pruned(note=row.coverage_note),
        },
    }


# ---------------------------------------------------------------------------------------------
# Match data
# ---------------------------------------------------------------------------------------------


def score_line(home: int | None, away: int | None) -> dict[str, Any]:
    """Both fields are nullable in the contract: an unplayed match really is `{home: null}`."""
    return {"home": home, "away": away}


def match_score(row: Match) -> dict[str, Any]:
    score = pruned(winner=row.score_winner, duration=row.score_duration)
    if row.score_full_time_home is not None or row.score_full_time_away is not None:
        score["full_time"] = score_line(row.score_full_time_home, row.score_full_time_away)
    if row.score_half_time_home is not None or row.score_half_time_away is not None:
        score["half_time"] = score_line(row.score_half_time_home, row.score_half_time_away)
    return score


def match(row: Match, *, competition_name: str, home: Team, away: Team) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.id,
        "competition": {"code": row.competition_code, "name": competition_name},
        "status": row.status,
        "utc_date": as_utc(row.utc_date),
        "home_team": team_summary(home),
        "away_team": team_summary(away),
        **pruned(
            season=row.season,
            matchday=row.matchday,
            stage=row.stage,
            venue=row.venue,
            last_updated=as_utc(row.last_updated),
        ),
    }
    score = match_score(row)
    if score:
        payload["score"] = score
    if row.referees:
        payload["referees"] = [
            pruned(
                id=official.get("id"),
                name=official.get("name"),
                type=official.get("type"),
                nationality=official.get("nationality"),
            )
            for official in row.referees
        ]
    return payload


def standing_row(row: Standing, team: Team) -> dict[str, Any]:
    return {
        "position": row.position,
        "team": team_summary(team),
        "played": row.played,
        "points": row.points,
        **pruned(
            won=row.won,
            drawn=row.drawn,
            lost=row.lost,
            goals_for=row.goals_for,
            goals_against=row.goals_against,
            goal_difference=row.goal_difference,
            form=row.form,
        ),
    }


def top_scorer(row: TopScorer, player: Player, team: Team) -> dict[str, Any]:
    return {
        "player": {"id": player.id, "name": player.name},
        "team": team_summary(team),
        "goals": row.goals,
        **pruned(
            played=row.played_matches,
            assists=row.assists,
            penalties=row.penalties,
        ),
    }


def top_scorers_table(
    *,
    code: str,
    name: str,
    season: int,
    snapshot: Any,
    scorers: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "competition": {"code": code, "name": name},
        "season": season,
        "snapshot": snapshot.isoformat(),
        "scorers": scorers,
    }


def standings_table(
    *,
    code: str,
    name: str,
    season: int,
    updated_at: Any,
    rows: list[dict[str, Any]],
    matchday: int | None = None,
    stage: str | None = None,
    group: str | None = None,
    table_type: str | None = None,
) -> dict[str, Any]:
    return {
        "competition": {"code": code, "name": name},
        "season": season,
        "updated_at": as_utc(updated_at),
        "table": rows,
        **pruned(matchday=matchday, stage=stage, group=group, type=table_type),
    }


# ---------------------------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------------------------


def ingest_error(entry: dict[str, Any]) -> dict[str, Any]:
    resource = str(entry.get("resource") or "") or None
    competition = None
    if resource:
        found = _COMPETITION_RESOURCE.match(resource)
        competition = found.group(1) if found else None
    return {
        "message": str(entry.get("message") or "unspecified ingestion error"),
        **pruned(competition=competition, resource=resource),
    }


def ingest_run(row: IngestRun, *, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = pruned(inserted=row.rows_inserted, updated=row.rows_updated, unchanged=row.rows_unchanged)
    payload: dict[str, Any] = {
        "id": row.id,
        "started_at": as_utc(row.started_at),
        "status": row.status,
        "trigger": row.trigger,
        "competitions": [str(code) for code in (row.competitions or [])],
        "errors": errors if errors is not None else [ingest_error(entry) for entry in (row.errors or [])],
        **pruned(
            finished_at=as_utc(row.finished_at),
            calls_used=row.calls_used,
            rate_limit_hits=row.rate_limit_hits,
            duration_seconds=row.duration_seconds,
        ),
    }
    if rows:
        payload["rows"] = rows
    return payload


def tool_call(entry: Any) -> dict[str, Any] | None:
    """One stored tool call, or None when it cannot be described.

    `ToolCall` requires a `name` and a `status`. A row that lacks either cannot be represented
    without inventing one of them, so it is dropped rather than dressed up: the turn still serves,
    and M4 - which writes these - is where a malformed call would be fixed. No turn exists yet.
    """
    if not isinstance(entry, dict) or not entry.get("name") or not entry.get("status"):
        return None
    # `args_summary` is an object in the contract. A stored string is not something to guess a shape
    # for, so it is left out rather than served as something the contract does not describe.
    args = entry.get("args_summary")
    return {
        "name": str(entry["name"]),
        "status": str(entry["status"]),
        **pruned(
            args_summary=args if isinstance(args, dict) else None,
            latency_ms=entry.get("latency_ms"),
            policy_decision=entry.get("policy_decision"),
        ),
    }


def agent_turn(row: AgentTurn) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_message": row.user_message,
        "answer": row.answer,
        "grounded": bool(row.grounded),
        "created_at": as_utc(row.created_at),
        "review_status": row.review_status,
        "tool_calls": [call for call in (tool_call(entry) for entry in (row.tool_calls or [])) if call is not None],
        **pruned(
            chat_id_hash=row.chat_id_hash,
            data_as_of=as_utc(row.data_as_of),
            model=row.model,
            latency_ms=row.latency_ms,
            review_note=row.review_note,
            # Rule 10: the route is recorded on every turn. Null means the turn predates routing
            # (M4), and the eval harness treats it as unscoreable rather than as correct.
            route=row.route,
            route_source=row.route_source,
            route_confidence=row.route_confidence,
        ),
    }


def knowledge_hit(chunk: KnowledgeChunk, score: float) -> dict[str, Any]:
    return {
        "chunk_id": chunk.id,
        "source_file": chunk.source_file,
        "heading": chunk.heading,
        "snippet": chunk.chunk_text[:SNIPPET_MAX_LENGTH],
        "score": min(1.0, max(0.0, float(score))),
        **pruned(updated_at=as_utc(chunk.updated_at)),
    }


def eval_run(row: EvalRun) -> dict[str, Any]:
    """One scoreboard row. `metrics` and `failure_reasons` are the harness's JSON, served as stored:
    the contract declares them open objects so the harness can add a metric without a migration."""
    return {
        "id": row.id,
        "set_name": row.set_name,
        "golden_set_sha256": row.golden_set_sha256,
        "prompt_version": row.prompt_version,
        "model": row.model,
        "git_commit": row.git_commit,
        "source": row.source,
        "status": row.status,
        "passed": bool(row.passed),
        "metrics": row.metrics or {},
        "failure_reasons": [str(reason) for reason in (row.failure_reasons or [])],
        "started_at": as_utc(row.started_at),
        "finished_at": as_utc(row.finished_at),
    }


def eval_result(row: EvalResult) -> dict[str, Any]:
    """One question inside a run. `route` and `scores` are required by the contract and may be
    `null`/`{}`; the optional fields are pruned rather than sent as nulls, as everywhere else here."""
    return {
        "id": row.id,
        "question_id": row.question_id,
        "class": row.class_name,
        "expected_route": row.expected_route,
        "route": row.route,
        "scores": row.scores or {},
        **pruned(
            expected_tool=row.expected_tool,
            tool=row.tool,
            retrieved=row.retrieved,
            latency_ms=row.latency_ms,
            error=row.error,
        ),
    }
