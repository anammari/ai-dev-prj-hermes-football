"""The turn-writer role: INSERT and SELECT on `agent_turns`, nothing else.

Rule 10 needs every turn recorded, but `agent_readonly` must stay read-only (rule 4). This migration
creates a second role for the gateway's own audit row only. It deliberately grants no default
privileges: a table added later is not writable by the agent until a migration says so.

Revision ID: 0003_agent_turn_writer
Revises: 0002_ingestion_storage
"""

from __future__ import annotations

import os
import re

from alembic import op

revision = "0003_agent_turn_writer"
down_revision = "0002_ingestion_storage"
branch_labels = None
depends_on = None

ROLE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _writer_role() -> tuple[str, str | None]:
    name = os.environ.get("AGENT_DB_WRITER_ROLE") or "agent_writer"
    if not ROLE_NAME_RE.match(name):
        raise RuntimeError(f"AGENT_DB_WRITER_ROLE is not a safe identifier: {name!r}")
    return name, os.environ.get("AGENT_DB_WRITER_PASSWORD") or None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    role, password = _writer_role()
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
    op.execute(f"GRANT INSERT, SELECT ON agent_turns TO {role}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON agent_turns FROM {role}")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    role, _ = _writer_role()
    op.execute(f"REVOKE ALL ON agent_turns FROM {role}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {role}")
    op.execute(f"DROP ROLE IF EXISTS {role}")
