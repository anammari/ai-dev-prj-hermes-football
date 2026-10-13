"""Bronze payloads and normalized scorer snapshots for M2.

Revision ID: 0002_ingestion_storage
Revises: 0001_init
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_ingestion_storage"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("competitions") as batch:
        batch.drop_constraint("ck_competitions_type_valid", type_="check")
        batch.create_check_constraint(
            "ck_competitions_type_valid",
            "type in ('LEAGUE', 'LEAGUE_CUP', 'CUP', 'PLAYOFFS', 'SUPER_CUP')",
        )
    with op.batch_alter_table("matches") as batch:
        batch.drop_constraint("ck_matches_status_valid", type_="check")
        batch.create_check_constraint(
            "ck_matches_status_valid",
            "status in ('SCHEDULED', 'TIMED', 'IN_PLAY', 'PAUSED', 'EXTRA_TIME', "
            "'PENALTY_SHOOTOUT', 'FINISHED', 'SUSPENDED', 'POSTPONED', 'CANCELLED', 'AWARDED')",
        )

    op.create_table(
        "raw_payloads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("request_params", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_raw_payloads"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["ingest_runs.id"], name="fk_raw_payloads_run_id_ingest_runs", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_raw_payloads_run_id", "raw_payloads", ["run_id"])

    op.create_table(
        "top_scorers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("competition_code", sa.String(length=8), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("played_matches", sa.Integer(), nullable=True),
        sa.Column("goals", sa.Integer(), nullable=True),
        sa.Column("assists", sa.Integer(), nullable=True),
        sa.Column("penalties", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_top_scorers"),
        sa.ForeignKeyConstraint(
            ["competition_code"], ["competitions.code"], name="fk_top_scorers_competition_code_competitions"
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["players.id"], name="fk_top_scorers_player_id_players", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name="fk_top_scorers_team_id_teams"),
        sa.UniqueConstraint(
            "competition_code",
            "season",
            "snapshot_date",
            "player_id",
            name="uq_top_scorer_snapshot_player",
        ),
    )
    op.create_index("ix_top_scorers_competition_season", "top_scorers", ["competition_code", "season"])


def downgrade() -> None:
    # The constraints this revision replaces cannot express the values it added, so fold the stored
    # data back to the nearest value the previous schema allows. Without this the ALTER fails on any
    # row already ingested with a new value — a knockout tie that went to extra time, or a league cup
    # — which makes the downgrade unusable exactly once the data matters.
    op.execute("UPDATE matches SET status = 'FINISHED' WHERE status IN ('EXTRA_TIME', 'PENALTY_SHOOTOUT')")
    op.execute("UPDATE competitions SET type = 'CUP' WHERE type = 'LEAGUE_CUP'")
    op.drop_index("ix_top_scorers_competition_season", table_name="top_scorers")
    op.drop_table("top_scorers")
    op.drop_index("ix_raw_payloads_run_id", table_name="raw_payloads")
    op.drop_table("raw_payloads")
    with op.batch_alter_table("matches") as batch:
        batch.drop_constraint("ck_matches_status_valid", type_="check")
        batch.create_check_constraint(
            "ck_matches_status_valid",
            "status in ('SCHEDULED', 'TIMED', 'IN_PLAY', 'PAUSED', 'FINISHED', 'SUSPENDED', "
            "'POSTPONED', 'CANCELLED', 'AWARDED')",
        )
    with op.batch_alter_table("competitions") as batch:
        batch.drop_constraint("ck_competitions_type_valid", type_="check")
        batch.create_check_constraint(
            "ck_competitions_type_valid", "type in ('LEAGUE', 'CUP', 'PLAYOFFS', 'SUPER_CUP')"
        )
