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
    """Whether the read path really connects as the read-only role.

    Two deployments reach that state: the usual one swaps the owner credentials for the agent role,
    and the M6 Compose service now hands the API an `agent_readonly` DSN in the first place so the
    owner password never enters the container. Both are read-only; a SQLite dev run is not.
    """
    if agent_database_url(settings) != settings.database_url:
        return True
    return settings.is_postgres and make_url(settings.database_url).username == settings.agent_db_role


def create_read_engine(settings: Settings) -> Engine:
    """The one engine the API holds. Reuses `db.session.create_db_engine`, so the SQLite foreign-key
    pragma and the pool settings stay in a single place."""
    return create_db_engine(replace(settings, database_url=agent_database_url(settings)))


def admin_database_url(settings: Settings) -> str:
    """The DSN of the one write path: the review decision, through the narrow `agent_admin` role.

    Deliberately a different role from `agent_readonly` and from the gateway's insert-only
    `agent_writer`: rule 4 stays true for the agent, and the dashboard's write is bounded by a grant
    (UPDATE on two columns) rather than by discipline. On SQLite there are no roles, so this falls
    back to the configured DSN exactly like the read engine does.
    """
    if not settings.is_postgres or not settings.admin_db_password or not settings.admin_db_role:
        return settings.database_url
    return make_url(settings.database_url).set(
        username=settings.admin_db_role,
        password=settings.admin_db_password,
    ).render_as_string(hide_password=False)


def create_admin_engine(settings: Settings) -> Engine:
    """The write engine, built only when an admin token is configured. `hide_parameters` masks the
    review body in driver errors, which is the same reason the turn writer sets it."""
    return create_db_engine(
        replace(settings, database_url=admin_database_url(settings)),
        hide_parameters=True,
    )
