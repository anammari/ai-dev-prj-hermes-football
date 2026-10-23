"""How `openapi.yaml` maps onto `db/models.py`, stated once so a test can hold both to it.

Every contract schema is either mapped to a table, or listed in `UNMAPPED_SCHEMAS` with the reason it
is not stored. Every property of a mapped schema has an expectation here, and every column of a mapped
table is either demanded by the contract or listed in `LOCAL_ONLY` with a reason. A contract field with
no home, or a column no contract field asks for, fails the test - which is the point: the schema and the
contract are supposed to be the same thing seen from two sides.
"""

from __future__ import annotations

# Expectation grammar, as strings so the map stays readable in a diff:
#   column:<name>      a column of this table with exactly that name
#   alias:<name>       the contract calls it something SQL cannot (or should not) use
#   nested:<Schema>    a nested object, flattened with the schema's own prefix
#   relation:<table>   stored in another table
#   json               kept as JSON in the column of the same name
#   derived:<reason>   computed per request, deliberately not stored
#   value:<reason>     a value object that lives in a column named by another property

SCHEMAS: dict[str, dict] = {
    "Competition": {
        "table": "competitions",
        "properties": {
            "code": "column:code",
            "name": "column:name",
            "area": "column:area",
            "type": "column:type",
            "current_season": "column:current_season",
            "season_start": "column:season_start",
            "season_end": "column:season_end",
            "coverage": "nested:Coverage",
        },
    },
    "Coverage": {
        "table": "competitions",
        # Reached as Competition.coverage, so its columns carry that property's name.
        "prefixes": ["coverage_"],
        "properties": {
            "fixtures": "column:fixtures",
            "standings": "column:standings",
            "scorers": "column:scorers",
            "lineups": "column:lineups",
            "live_scores": "column:live_scores",
            "note": "column:note",
        },
    },
    "StandingRow": {
        "table": "standings",
        "properties": {
            "position": "column:position",
            "team": "alias:team_id",
            "played": "column:played",
            "won": "column:won",
            "drawn": "column:drawn",
            "lost": "column:lost",
            "goals_for": "column:goals_for",
            "goals_against": "column:goals_against",
            "goal_difference": "column:goal_difference",
            "points": "column:points",
            "form": "column:form",
        },
    },
    "StandingsTable": {
        "table": "standings",
        "properties": {
            "competition": "alias:competition_code",
            "season": "column:season",
            "matchday": "column:matchday",
            "stage": "column:stage",
            "group": "alias:group_label",
            "type": "alias:table_type",
            "updated_at": "column:updated_at",
            "table": "derived:the rows of the table are the standing rows themselves",
        },
    },
    "TopScorersTable": {
        "table": "top_scorers",
        "properties": {
            "competition": "alias:competition_code",
            "season": "column:season",
            "snapshot": "alias:snapshot_date",
            "scorers": "derived:the rows of this snapshot, ordered by goals then assists",
        },
    },
    "TopScorer": {
        "table": "top_scorers",
        "properties": {
            "player": "relation:players",
            "team": "relation:teams",
            "goals": "column:goals",
            "played": "alias:played_matches",
            "assists": "column:assists",
            "penalties": "column:penalties",
        },
    },
    "TeamSummary": {
        "table": "teams",
        "properties": {
            "id": "column:id",
            "name": "column:name",
            "tla": "column:tla",
            "crest": "column:crest",
        },
    },
    "TeamDetail": {
        "table": "teams",
        "extends": "TeamSummary",
        "properties": {
            "area": "column:area",
            "founded": "column:founded",
            "venue": "column:venue",
            "club_colors": "column:club_colors",
            "competitions": "relation:team_competitions",
            "squad_available": "derived:true when players rows exist for the team",
            "squad_size": "derived:count of players rows for the team",
        },
    },
    "Match": {
        "table": "matches",
        "properties": {
            "id": "column:id",
            "competition": "alias:competition_code",
            "season": "column:season",
            "matchday": "column:matchday",
            "stage": "column:stage",
            "status": "column:status",
            "utc_date": "column:utc_date",
            "home_team": "alias:home_team_id",
            "away_team": "alias:away_team_id",
            "score": "nested:Score",
            "venue": "column:venue",
            "referees": "json",
            "last_updated": "column:last_updated",
        },
    },
    "Score": {
        "table": "matches",
        "prefixes": ["score_"],
        "properties": {
            "winner": "column:winner",
            "duration": "column:duration",
            "full_time": "nested:ScoreLine",
            "half_time": "nested:ScoreLine",
        },
    },
    "ScoreLine": {
        "table": "matches",
        # Nested two levels deep: its prefix is whatever `Score` was reached with, so the columns are
        # spelled out per parent property and never resolved on their own.
        "nested_only": True,
        "prefixes": ["score_full_time_", "score_half_time_"],
        "properties": {
            "home": "column:home",
            "away": "column:away",
        },
    },
    "KnowledgeHit": {
        "table": "knowledge_chunks",
        "properties": {
            "chunk_id": "alias:id",
            "source_file": "column:source_file",
            "heading": "column:heading",
            "snippet": "alias:chunk_text",
            "score": "derived:cosine similarity, computed for the query that asked",
            "updated_at": "column:updated_at",
        },
    },
    "AgentTurn": {
        "table": "agent_turns",
        "properties": {
            "id": "column:id",
            "chat_id_hash": "column:chat_id_hash",
            "user_message": "column:user_message",
            "tool_calls": "json",
            "answer": "column:answer",
            "grounded": "column:grounded",
            "data_as_of": "column:data_as_of",
            "model": "column:model",
            "latency_ms": "column:latency_ms",
            "review_status": "column:review_status",
            "review_note": "column:review_note",
            "route": "column:route",
            "route_source": "column:route_source",
            "route_confidence": "column:route_confidence",
            "created_at": "column:created_at",
        },
    },
    "IngestRun": {
        "table": "ingest_runs",
        "properties": {
            "id": "column:id",
            "started_at": "column:started_at",
            "finished_at": "column:finished_at",
            "status": "column:status",
            "trigger": "column:trigger",
            "competitions": "json",
            "calls_used": "column:calls_used",
            "rate_limit_hits": "column:rate_limit_hits",
            "rows": "nested:IngestRunRows",
            "errors": "json",
            "duration_seconds": "column:duration_seconds",
        },
    },
    "IngestRunRows": {
        # Not a schema of its own: the contract inlines this object under IngestRun.rows.
        "inline": True,
        "table": "ingest_runs",
        "prefixes": ["rows_"],
        "properties": {
            "inserted": "column:inserted",
            "updated": "column:updated",
            "unchanged": "column:unchanged",
        },
    },
}

#: Contract schemas with no table of their own, and why.
UNMAPPED_SCHEMAS: dict[str, str] = {
    "CompetitionCode": "an enum; the codes are rows in competitions, not a type",
    "MatchStatus": "an enum; it is the type of matches.status",
    "ReviewStatus": "an enum; it is the type of agent_turns.review_status",
    "ToolCall": "a value object stored inside agent_turns.tool_calls (JSON)",
    "ResponseMeta": "per-response envelope, assembled by the API",
    "Pagination": "per-response envelope, assembled by the API",
    "HealthCheck": "runtime probe of the API and the schema revision",
    "MatchList": "response envelope around matches",
    "AgentTurnList": "response envelope around agent_turns",
    "IngestRunList": "response envelope around ingest_runs",
    "KnowledgeSearchResult": "response envelope around knowledge hits",
    "ErrorResponse": "per-response envelope, assembled by the API",
    "TeamForm": "computed from matches over a window (R-F4.x); never stored",
    "FreshnessReport": "computed from ingest_runs per request (R-F9.3)",
    "HeadToHead": "computed from stored matches: the upstream aggregates are wrong (openapi notes)",
}

#: Tables that exist for local bookkeeping rather than to serve a contract schema.
LOCAL_TABLES: dict[str, str] = {
    "seasons": "the contract carries `season` as an integer; this table is the local catalog of them",
    "team_competitions": "the join behind TeamDetail.competitions",
    "players": "the contract exposes only squad_available/squad_size, never a player list",
    "raw_payloads": "bronze retention of upstream responses, not served to the agent",
    "alembic_version": "Alembic's own bookkeeping",
}

#: Columns no contract property asks for, with the reason each one exists.
LOCAL_ONLY: dict[str, dict[str, str]] = {
    "competitions": {"updated_at": "when our ingestion last wrote the row"},
    "seasons": {
        "*": "see LOCAL_TABLES['seasons']",
    },
    "teams": {"updated_at": "when our ingestion last wrote the row"},
    "team_competitions": {"*": "see LOCAL_TABLES['team_competitions']"},
    "players": {"*": "see LOCAL_TABLES['players']"},
    "matches": {"updated_at": "when our ingestion last wrote the row; last_updated is the provider's"},
    "standings": {
        "id": "surrogate key; the contract identifies a row by team and snapshot",
        "snapshot_date": "which day's table this row came from, so old snapshots stay queryable",
        "updated_at": "when our ingestion last wrote the row",
    },
    "ingest_runs": {"created_at": "when our ingestion created the row"},
    "top_scorers": {
        "id": "surrogate key; a row is identified by competition, season, snapshot and player",
        "player_id": "the relation behind TopScorer.player",
        "team_id": "the relation behind TopScorer.team",
    },
    "raw_payloads": {"*": "see LOCAL_TABLES['raw_payloads']"},
    "knowledge_chunks": {
        "id": "surrogate uuid; the contract calls it chunk_id",
        "ordinal": "position of the passage inside its file, so chunks stay ordered and unique",
        "embedding": "the vector itself, vector(768) on Postgres",
        "embedding_model": "which model produced the vector, so a model change is a detectable re-index",
        "embedding_dim": "the width actually returned, checked against the migration",
        "content_hash": "hash of the source file, which is how staleness is decided without a model",
        "updated_at": "when the chunk was last written",
    },
    "agent_turns": {},
}
