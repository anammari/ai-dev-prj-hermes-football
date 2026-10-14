"""The database connection the API reads through.

One hard rule decides the shape of this module: *the agent's data path is read-only* (`AGENTS.md`
rule 4). So the engine every request handler uses is built to log in as `agent_readonly` whenever the
deployment supplies a password for that role (Compose does, from `.env`), and the API has no write
engine at all in M3.

On the SQLite dev fallback there are no roles, so the same engine is reused and `read_only` is False;
the integration suite checks the role against real Postgres instead, which is where the claim can
actually be falsified (`_docs/data-model.md`).
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import Engine, make_url

from db.session import create_db_engine
from db.settings import Settings


def agent_database_url(settings: Settings) -> str:
    """The DSN the request path must use: the read-only role when one is configured.

    Falls back to the configured DSN when there is nothing to switch to (SQLite, or a Postgres
    deployment that has not set `AGENT_DB_PASSWORD`). The fallback is visible rather than silent:
    `read_only` reports which of the two happened and the startup log prints it.
    """
    if not settings.is_postgres or not settings.agent_db_password or not settings.agent_db_role:
        return settings.database_url
    return make_url(settings.database_url).set(
        username=settings.agent_db_role,
        password=settings.agent_db_password,
    ).render_as_string(hide_password=False)


def read_only(settings: Settings) -> bool:
    """Whether the read path really connects as a different, read-only role."""
    return agent_database_url(settings) != settings.database_url


def create_read_engine(settings: Settings) -> Engine:
    """The one engine the API holds. Reuses `db.session.create_db_engine`, so the SQLite foreign-key
    pragma and the pool settings stay in a single place."""
    return create_db_engine(replace(settings, database_url=agent_database_url(settings)))
