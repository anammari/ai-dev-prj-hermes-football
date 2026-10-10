"""Engine and session helpers.

One engine per process, built from `Settings`. SQLite needs `check_same_thread=False` (tests and
scripts share a connection across threads); Postgres needs nothing special.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from db.settings import Settings


def create_db_engine(settings: Settings, *, echo: bool = False) -> Engine:
    kwargs: dict = {"future": True, "echo": echo, "pool_pre_ping": True}
    if not settings.is_postgres:
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(settings.database_url, **kwargs)
    if not settings.is_postgres:
        # SQLite ignores foreign keys unless asked, and an unenforced foreign key is a test that
        # passes for the wrong reason. Postgres always enforces them; the dev fallback should too.
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection: object, _record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit on success, roll back on failure, always close."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
