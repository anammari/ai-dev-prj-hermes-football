"""Initial schema: catalog, match data, ingestion ledger, knowledge index, agent turns.

Matches `openapi.yaml` v0.1.0 and `db/models.py`. Two things here exist only on Postgres and are
skipped on the SQLite dev fallback:

* the `vector` extension and the HNSW index on `knowledge_chunks.embedding` (pgvector),
* the read-only role the agent-facing path uses (`R-F2.4`), its SELECT grants, and the
  default privileges that keep future tables read-only for it too.

Every constraint is named explicitly. Alembic's `op.create_table` does not apply the models' naming
convention, so leaving them unnamed would let Postgres pick names we then have to guess when
dropping them later.

Revision ID: 0001_init
Revises:
Create Date: 2026-10-10
"""

from __future__ import annotations

import os
import re

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None

#: Pinned native output width of `embeddinggemma:300m` (`_docs/decisions/0002`). One constant, in
#: the migration, because the column width is a schema fact; `tests/test_embedding_probe.py` fails if
#: the provider ever returns a different width.
EMBEDDING_DIM = 768

ROLE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _embedding_type() -> sa.types.TypeEngine:
    return Vector(EMBEDDING_DIM) if _is_postgres() else sa.Text()


def _agent_role() -> tuple[str, str | None]:
    """Role name and optional password, taken from the environment and validated.

    The name reaches an `ALTER ROLE` statement, which cannot take bind parameters, so it is checked
    against a strict pattern instead. The password is only set when one is supplied: tests use
    `SET ROLE` and never need the role to log in.
    """
    name = os.environ.get("AGENT_DB_ROLE") or "agent_readonly"
    if not ROLE_NAME_RE.match(name):
        raise RuntimeError(f"AGENT_DB_ROLE is not a safe identifier: {name!r}")
    return name, os.environ.get("AGENT_DB_PASSWORD") or None


def upgrade() -> None:
    if _is_postgres():
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "competitions",
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("area", sa.String(length=120), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=True),
        sa.Column("current_season", sa.Integer(), nullable=True),
        sa.Column("season_start", sa.Date(), nullable=True),
        sa.Column("season_end", sa.Date(), nullable=True),
        sa.Column("coverage_fixtures", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("coverage_standings", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("coverage_scorers", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("coverage_lineups", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("coverage_live_scores", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("coverage_note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("code", name="pk_competitions"),
        sa.CheckConstraint("type in ('LEAGUE', 'CUP', 'PLAYOFFS', 'SUPER_CUP')", name="ck_competitions_type_valid"),
    )

    op.create_table(
        "seasons",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("competition_code", sa.String(length=8), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_seasons"),
        sa.ForeignKeyConstraint(
            ["competition_code"],
            ["competitions.code"],
            name="fk_seasons_competition_code_competitions",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("competition_code", "year", name="uq_seasons_competition_code_year"),
    )

    op.create_table(
        "teams",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("tla", sa.String(length=8), nullable=True),
        sa.Column("crest", sa.String(length=255), nullable=True),
        sa.Column("area", sa.String(length=120), nullable=True),
        sa.Column("founded", sa.Integer(), nullable=True),
        sa.Column("venue", sa.String(length=160), nullable=True),
        sa.Column("club_colors", sa.String(length=80), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_teams"),
    )

    op.create_table(
        "team_competitions",
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("competition_code", sa.String(length=8), nullable=False),
        sa.PrimaryKeyConstraint("team_id", "competition_code", name="pk_team_competitions"),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name="fk_team_competitions_team_id_teams", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["competition_code"],
            ["competitions.code"],
            name="fk_team_competitions_competition_code_competitions",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "players",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("position", sa.String(length=40), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("nationality", sa.String(length=80), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_players"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name="fk_players_team_id_teams", ondelete="CASCADE"),
    )
    op.create_index("ix_players_team_id", "players", ["team_id"])

    op.create_table(
        "matches",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("competition_code", sa.String(length=8), nullable=False),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("matchday", sa.Integer(), nullable=True),
        sa.Column("stage", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("utc_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("home_team_id", sa.BigInteger(), nullable=False),
        sa.Column("away_team_id", sa.BigInteger(), nullable=False),
        sa.Column("score_winner", sa.String(length=16), nullable=True),
        sa.Column("score_duration", sa.String(length=16), nullable=True),
        sa.Column("score_full_time_home", sa.Integer(), nullable=True),
        sa.Column("score_full_time_away", sa.Integer(), nullable=True),
        sa.Column("score_half_time_home", sa.Integer(), nullable=True),
        sa.Column("score_half_time_away", sa.Integer(), nullable=True),
        sa.Column("venue", sa.String(length=160), nullable=True),
        sa.Column("referees", sa.JSON(), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_matches"),
        sa.ForeignKeyConstraint(
            ["competition_code"], ["competitions.code"], name="fk_matches_competition_code_competitions"
        ),
        sa.ForeignKeyConstraint(["home_team_id"], ["teams.id"], name="fk_matches_home_team_id_teams"),
        sa.ForeignKeyConstraint(["away_team_id"], ["teams.id"], name="fk_matches_away_team_id_teams"),
        sa.CheckConstraint(
            "status in ('SCHEDULED', 'TIMED', 'IN_PLAY', 'PAUSED', 'FINISHED', 'SUSPENDED', "
            "'POSTPONED', 'CANCELLED', 'AWARDED')",
            name="ck_matches_status_valid",
        ),
    )
    op.create_index("ix_matches_utc_date", "matches", ["utc_date"])
    op.create_index("ix_matches_competition_season", "matches", ["competition_code", "season"])
    op.create_index("ix_matches_home_team_id", "matches", ["home_team_id"])
    op.create_index("ix_matches_away_team_id", "matches", ["away_team_id"])

    op.create_table(
        "standings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("competition_code", sa.String(length=8), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("matchday", sa.Integer(), nullable=True),
        sa.Column("stage", sa.String(length=64), nullable=True),
        sa.Column("group_label", sa.String(length=40), nullable=True),
        sa.Column("table_type", sa.String(length=8), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("played", sa.Integer(), nullable=False),
        sa.Column("won", sa.Integer(), nullable=True),
        sa.Column("drawn", sa.Integer(), nullable=True),
        sa.Column("lost", sa.Integer(), nullable=True),
        sa.Column("goals_for", sa.Integer(), nullable=True),
        sa.Column("goals_against", sa.Integer(), nullable=True),
        sa.Column("goal_difference", sa.Integer(), nullable=True),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("form", sa.String(length=10), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_standings"),
        sa.ForeignKeyConstraint(
            ["competition_code"], ["competitions.code"], name="fk_standings_competition_code_competitions"
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name="fk_standings_team_id_teams"),
        sa.CheckConstraint("table_type in ('TOTAL', 'HOME', 'AWAY')", name="ck_standings_table_type_valid"),
        sa.UniqueConstraint(
            "competition_code",
            "season",
            "snapshot_date",
            "table_type",
            "team_id",
            # Shorter than the naming convention allows: Postgres caps identifiers at 63 bytes and the
            # spelled-out name is 67.
            name="uq_standings_snapshot_team",
        ),
    )
    op.create_index("ix_standings_competition_season", "standings", ["competition_code", "season"])

    op.create_table(
        "ingest_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("competitions", sa.JSON(), nullable=True),
        sa.Column("calls_used", sa.Integer(), nullable=True),
        sa.Column("rate_limit_hits", sa.Integer(), nullable=True),
        sa.Column("rows_inserted", sa.Integer(), nullable=True),
        sa.Column("rows_updated", sa.Integer(), nullable=True),
        sa.Column("rows_unchanged", sa.Integer(), nullable=True),
        sa.Column("errors", sa.JSON(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ingest_runs"),
        sa.CheckConstraint(
            "status in ('running', 'succeeded', 'partial', 'failed')", name="ck_ingest_runs_status_valid"
        ),
        sa.CheckConstraint("trigger in ('schedule', 'manual')", name="ck_ingest_runs_trigger_valid"),
    )
    op.create_index("ix_ingest_runs_started_at", "ingest_runs", ["started_at"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_file", sa.String(length=255), nullable=False),
        sa.Column("heading", sa.String(length=255), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", _embedding_type(), nullable=False),
        sa.Column("embedding_model", sa.String(length=64), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_chunks"),
        sa.UniqueConstraint(
            "source_file", "heading", "ordinal", name="uq_knowledge_chunks_source_file_heading_ordinal"
        ),
    )
    op.create_index("ix_knowledge_chunks_source_file", "knowledge_chunks", ["source_file"])
    if _is_postgres():
        # Cosine distance, because the embedding client normalises what it writes. HNSW because the
        # corpus is read on every knowledge question and 768 dimensions is well inside pgvector's
        # 2000-dimension index limit.
        op.create_index(
            "ix_knowledge_chunks_embedding_hnsw",
            "knowledge_chunks",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )

    op.create_table(
        "agent_turns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("chat_id_hash", sa.String(length=64), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("grounded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("data_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model", sa.String(length=80), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("review_status", sa.String(length=16), server_default=sa.text("'unreviewed'"), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("route", sa.String(length=16), nullable=True),
        sa.Column("route_source", sa.String(length=16), nullable=True),
        sa.Column("route_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_agent_turns"),
        sa.CheckConstraint(
            "review_status in ('unreviewed', 'correct', 'flagged', 'wrong')",
            name="ck_agent_turns_review_status_valid",
        ),
        sa.CheckConstraint("route in ('tool', 'knowledge', 'clarify', 'refuse')", name="ck_agent_turns_route_valid"),
        sa.CheckConstraint("route_source in ('rules', 'model', 'fallback')", name="ck_agent_turns_route_source_valid"),
    )
    op.create_index("ix_agent_turns_created_at", "agent_turns", ["created_at"])

    if _is_postgres():
        _grant_read_only_role()


def _grant_read_only_role() -> None:
    """Create the agent-facing role and give it SELECT and nothing else.

    Row-level reads on future tables are covered by the default privileges, so a table added by a
    later migration does not silently become invisible (or writable) to the agent.
    """
    role, password = _agent_role()
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    if password:
        escaped = password.replace("'", "''")
        op.execute(f"ALTER ROLE {role} WITH LOGIN PASSWORD '{escaped}'")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {role}")


def downgrade() -> None:
    if _is_postgres():
        role, _ = _agent_role()
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM {role}")
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {role}")
        op.execute(f"DROP ROLE IF EXISTS {role}")

    op.drop_index("ix_agent_turns_created_at", table_name="agent_turns")
    op.drop_table("agent_turns")
    if _is_postgres():
        op.drop_index("ix_knowledge_chunks_embedding_hnsw", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_source_file", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_ingest_runs_started_at", table_name="ingest_runs")
    op.drop_table("ingest_runs")
    op.drop_index("ix_standings_competition_season", table_name="standings")
    op.drop_table("standings")
    op.drop_index("ix_matches_away_team_id", table_name="matches")
    op.drop_index("ix_matches_home_team_id", table_name="matches")
    op.drop_index("ix_matches_competition_season", table_name="matches")
    op.drop_index("ix_matches_utc_date", table_name="matches")
    op.drop_table("matches")
    op.drop_index("ix_players_team_id", table_name="players")
    op.drop_table("players")
    op.drop_table("team_competitions")
    op.drop_table("teams")
    op.drop_table("seasons")
    op.drop_table("competitions")
    # The `vector` extension is left in place: it is database-wide, may predate this migration, and
    # dropping it would break any other schema that uses it.
