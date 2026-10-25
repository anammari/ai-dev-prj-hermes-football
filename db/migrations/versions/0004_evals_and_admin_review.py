"""The eval scoreboard's tables, and the role the review button writes through.

Two changes, both M5:

* `eval_runs` and `eval_results` store what `make eval` measured. They are written by the eval
  harness with the owner URL (like a migration), never by the request path, and read by the API
  through `agent_readonly`, which already has default SELECT on tables created by this owner.
* `agent_admin` is a third role, narrower than `agent_writer`: UPDATE only the two review columns of
  `agent_turns`, plus SELECT on that table so the PATCH can return the updated row. No default
  privileges, so a table added later is not writable by the dashboard until a migration says so.

Rule 4 still holds after this migration: the agent's read role is unchanged, the MCP server and the
gateway hold no admin credentials, and the one write the API can make is the human review decision.

Revision ID: 0004_evals_and_admin_review
Revises: 0003_agent_turn_writer
"""

from __future__ import annotations

import os
import re

import sqlalchemy as sa
from alembic import op

revision = "0004_evals_and_admin_review"
down_revision = "0003_agent_turn_writer"
branch_labels = None
depends_on = None

ROLE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _admin_role() -> tuple[str, str | None]:
    name = os.environ.get("AGENT_ADMIN_DB_ROLE") or "agent_admin"
    if not ROLE_NAME_RE.match(name):
        raise RuntimeError(f"AGENT_ADMIN_DB_ROLE is not a safe identifier: {name!r}")
    return name, os.environ.get("AGENT_ADMIN_DB_PASSWORD") or None


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("set_name", sa.String(length=80), nullable=False),
        sa.Column("golden_set_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("git_commit", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=16), server_default="live", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="running", nullable=False),
        sa.Column("passed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("failure_reasons", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source in ('live', 'backfill')", name="ck_eval_runs_source_valid"
        ),
        sa.CheckConstraint(
            "status in ('running', 'succeeded', 'failed')", name="ck_eval_runs_status_valid"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_runs"),
    )
    op.create_index("ix_eval_runs_started_at", "eval_runs", ["started_at"])
    op.create_index("ix_eval_runs_set_name", "eval_runs", ["set_name"])

    op.create_table(
        "eval_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=64), nullable=False),
        sa.Column("class_name", sa.String(length=40), nullable=False),
        sa.Column("expected_route", sa.String(length=16), nullable=False),
        sa.Column("expected_tool", sa.String(length=64), nullable=True),
        sa.Column("route", sa.String(length=16), nullable=True),
        sa.Column("tool", sa.String(length=64), nullable=True),
        sa.Column("retrieved", sa.JSON(), nullable=True),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "expected_route in ('tool', 'knowledge', 'clarify', 'refuse')",
            name="ck_eval_results_expected_route_valid",
        ),
        sa.CheckConstraint(
            "route in ('tool', 'knowledge', 'clarify', 'refuse')", name="ck_eval_results_route_valid"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["eval_runs.id"],
            name="fk_eval_results_run_id_eval_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_results"),
        sa.UniqueConstraint("run_id", "question_id", name="uq_eval_results_run_id_question_id"),
    )
    op.create_index("ix_eval_results_run_id", "eval_results", ["run_id"])

    _create_admin_role()


def _create_admin_role() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    role, password = _admin_role()
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
    op.execute(f"GRANT SELECT ON agent_turns TO {role}")
    # Column-level UPDATE: the review decision, and nothing else on the row. A grant on the whole
    # table would let the dashboard rewrite the answer it is reviewing, which is the audit trail.
    op.execute(f"GRANT UPDATE (review_status, review_note) ON agent_turns TO {role}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        role, _ = _admin_role()
        op.execute(f"REVOKE ALL ON agent_turns FROM {role}")
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {role}")
        op.execute(f"DROP ROLE IF EXISTS {role}")
    op.drop_index("ix_eval_results_run_id", table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_index("ix_eval_runs_set_name", table_name="eval_runs")
    op.drop_index("ix_eval_runs_started_at", table_name="eval_runs")
    op.drop_table("eval_runs")
