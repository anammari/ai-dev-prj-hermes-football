"""SQLAlchemy models for Hermes Football.

Column names follow `openapi.yaml` wherever the contract names the same concept, so
`tests/test_contract_coverage.py` can check this schema against the contract by name rather than by
memory. Nested contract objects are flattened with their parent name as a prefix
(`score.full_time.home` -> `score_full_time_home`), and arrays of objects are stored as JSON with the
contract's own name.

Anything the contract *derives* rather than stores has no table here on purpose: head-to-head
counts (computed by the API because the upstream aggregates are wrong), team form, the freshness
report, and the response envelopes. `_docs/data-model.md` lists them.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from db.types import EMBEDDING_DIM, Embedding

#: Deterministic constraint names, so a migration diff is readable and a constraint can be dropped
#: by name later.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

MATCH_STATUSES = (
    "SCHEDULED",
    "TIMED",
    "IN_PLAY",
    "PAUSED",
    "FINISHED",
    "SUSPENDED",
    "POSTPONED",
    "CANCELLED",
    "AWARDED",
)
COMPETITION_TYPES = ("LEAGUE", "CUP", "PLAYOFFS", "SUPER_CUP")
STANDINGS_TYPES = ("TOTAL", "HOME", "AWAY")
INGEST_STATUSES = ("running", "succeeded", "partial", "failed")
INGEST_TRIGGERS = ("schedule", "manual")
REVIEW_STATUSES = ("unreviewed", "correct", "flagged", "wrong")
ROUTES = ("tool", "knowledge", "clarify", "refuse")
ROUTE_SOURCES = ("rules", "model", "fallback")


def _enum_check(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    joined = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} in ({joined})", name=name)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def new_id() -> str:
    return str(uuid.uuid4())


class Timestamped:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------------------------
# Catalog: competitions, seasons, teams, squads
# ---------------------------------------------------------------------------------------------


class Competition(Base, Timestamped):
    """`Competition` plus its `Coverage` block.

    `Coverage` is flattened into explicit flags. The contract says the block is locally maintained
    rather than scraped, so the values belong in reviewable columns, not in a JSON blob nobody reads.
    """

    __tablename__ = "competitions"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    area: Mapped[str | None] = mapped_column(String(120))
    type: Mapped[str | None] = mapped_column(String(16))
    current_season: Mapped[int | None] = mapped_column(Integer)
    season_start: Mapped[date | None] = mapped_column(Date)
    season_end: Mapped[date | None] = mapped_column(Date)
    coverage_fixtures: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    coverage_standings: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    coverage_scorers: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    coverage_lineups: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    coverage_live_scores: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    coverage_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (_enum_check("type", COMPETITION_TYPES, "type_valid"),)


class Season(Base):
    """One season of one competition. `season` in upstream payloads is its `year`."""

    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    competition_code: Mapped[str] = mapped_column(ForeignKey("competitions.code", ondelete="CASCADE"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("competition_code", "year"),)


class Team(Base, Timestamped):
    """`TeamSummary` and the `TeamDetail` extras. The id is the provider's id, not ours."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    tla: Mapped[str | None] = mapped_column(String(8))
    crest: Mapped[str | None] = mapped_column(String(255))
    area: Mapped[str | None] = mapped_column(String(120))
    founded: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(String(160))
    club_colors: Mapped[str | None] = mapped_column(String(80))


class TeamCompetition(Base):
    """`TeamDetail.competitions`: which competitions a team appears in."""

    __tablename__ = "team_competitions"

    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    competition_code: Mapped[str] = mapped_column(ForeignKey("competitions.code", ondelete="CASCADE"), primary_key=True)


class Player(Base, Timestamped):
    """Squad members. The free tier does return squads (verified 2026-10-10), so this table is real,
    but the agent may only answer player questions when rows exist for the team and
    `squad_available` is true in the API response."""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    position: Mapped[str | None] = mapped_column(String(40))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    nationality: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (Index("ix_players_team_id", "team_id"),)


# ---------------------------------------------------------------------------------------------
# Match data: matches, standings
# ---------------------------------------------------------------------------------------------


class Match(Base, Timestamped):
    """`Match`. `score` is flattened; `referees` stays JSON because it is published as a list of
    objects with no key of its own and is never queried by field."""

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    competition_code: Mapped[str] = mapped_column(ForeignKey("competitions.code"), nullable=False)
    season: Mapped[int | None] = mapped_column(Integer)
    matchday: Mapped[int | None] = mapped_column(Integer)
    stage: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    utc_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    score_winner: Mapped[str | None] = mapped_column(String(16))
    score_duration: Mapped[str | None] = mapped_column(String(16))
    score_full_time_home: Mapped[int | None] = mapped_column(Integer)
    score_full_time_away: Mapped[int | None] = mapped_column(Integer)
    score_half_time_home: Mapped[int | None] = mapped_column(Integer)
    score_half_time_away: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(String(160))
    referees: Mapped[list | None] = mapped_column(JSON)
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        _enum_check("status", MATCH_STATUSES, "status_valid"),
        Index("ix_matches_utc_date", "utc_date"),
        Index("ix_matches_competition_season", "competition_code", "season"),
        Index("ix_matches_home_team_id", "home_team_id"),
        Index("ix_matches_away_team_id", "away_team_id"),
    )


class Standing(Base, Timestamped):
    """One `StandingRow` of a `StandingsTable`.

    `StandingRow.team` becomes `team_id`; `StandingsTable.group` becomes `group_label` because
    `group` is a reserved word in SQL. Both aliases are declared in the contract test.
    """

    __tablename__ = "standings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    competition_code: Mapped[str] = mapped_column(ForeignKey("competitions.code"), nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    matchday: Mapped[int | None] = mapped_column(Integer)
    stage: Mapped[str | None] = mapped_column(String(64))
    group_label: Mapped[str | None] = mapped_column(String(40))
    table_type: Mapped[str | None] = mapped_column(String(8))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    played: Mapped[int] = mapped_column(Integer, nullable=False)
    won: Mapped[int | None] = mapped_column(Integer)
    drawn: Mapped[int | None] = mapped_column(Integer)
    lost: Mapped[int | None] = mapped_column(Integer)
    goals_for: Mapped[int | None] = mapped_column(Integer)
    goals_against: Mapped[int | None] = mapped_column(Integer)
    goal_difference: Mapped[int | None] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    form: Mapped[str | None] = mapped_column(String(10))

    __table_args__ = (
        _enum_check("table_type", STANDINGS_TYPES, "table_type_valid"),
        # Named by hand: the naming convention would spell out all five columns and overflow Postgres's
        # 63-byte identifier limit (the migration carries the same name).
        UniqueConstraint(
            "competition_code",
            "season",
            "snapshot_date",
            "table_type",
            "team_id",
            name="uq_standings_snapshot_team",
        ),
        Index("ix_standings_competition_season", "competition_code", "season"),
    )


# ---------------------------------------------------------------------------------------------
# Operations: ingestion ledger, knowledge index, agent turns
# ---------------------------------------------------------------------------------------------


class IngestRun(Base):
    """`IngestRun`: one row per ingestion run. `competitions` and `errors` are JSON because the
    contract publishes them as arrays of values, not as relations worth joining."""

    __tablename__ = "ingest_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    competitions: Mapped[list | None] = mapped_column(JSON)
    calls_used: Mapped[int | None] = mapped_column(Integer)
    rate_limit_hits: Mapped[int | None] = mapped_column(Integer)
    rows_inserted: Mapped[int | None] = mapped_column(Integer)
    rows_updated: Mapped[int | None] = mapped_column(Integer)
    rows_unchanged: Mapped[int | None] = mapped_column(Integer)
    errors: Mapped[list | None] = mapped_column(JSON)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        _enum_check("status", INGEST_STATUSES, "status_valid"),
        _enum_check("trigger", INGEST_TRIGGERS, "trigger_valid"),
        Index("ix_ingest_runs_started_at", "started_at"),
    )


class KnowledgeChunk(Base, Timestamped):
    """`KnowledgeHit`: one chunk of one hand-written note.

    The files in `hermes/agent-knowledge/` are the source of truth (`_docs/decisions/0001`); this
    table is a derived index. `content_hash` is the hash of the *whole source file* at the time the
    chunk was written, which is how the indexer decides a file is stale without asking a model
    (`R-F6.4`). `embedding_model` and `embedding_dim` are stored so that changing either is a
    detectable re-index rather than a silently mixed vector space.
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_file: Mapped[str] = mapped_column(String(255), nullable=False)
    heading: Mapped[str] = mapped_column(String(255), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Embedding(EMBEDDING_DIM), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("source_file", "heading", "ordinal"),
        Index("ix_knowledge_chunks_source_file", "source_file"),
    )


class AgentTurn(Base):
    """`AgentTurn`, including the routing columns from `R-F6.6`. `chat_id_hash` is a salted hash:
    the raw Telegram chat id never reaches the database (`AGENTS.md` rule 6)."""

    __tablename__ = "agent_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chat_id_hash: Mapped[str | None] = mapped_column(String(64))
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[list | None] = mapped_column(JSON)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    data_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model: Mapped[str | None] = mapped_column(String(80))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unreviewed")
    review_note: Mapped[str | None] = mapped_column(Text)
    route: Mapped[str | None] = mapped_column(String(16))
    route_source: Mapped[str | None] = mapped_column(String(16))
    route_confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        _enum_check("review_status", REVIEW_STATUSES, "review_status_valid"),
        _enum_check("route", ROUTES, "route_valid"),
        _enum_check("route_source", ROUTE_SOURCES, "route_source_valid"),
        Index("ix_agent_turns_created_at", "created_at"),
    )
