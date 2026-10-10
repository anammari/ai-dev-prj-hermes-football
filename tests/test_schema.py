"""The migration *is* the schema: apply it, then hold the models to it.

`alembic check` (via `compare_metadata`) is the useful half of this file. It catches the failure mode
that hurts: a model edited without a migration, discovered months later when the drift has become
somebody's outage. The rest of the file proves the constraints do something.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import (
    EMBEDDING_DIM,
    Base,
    Competition,
    KnowledgeChunk,
    Match,
    Standing,
    Team,
)

MATCH = {
    "id": 419823,
    "competition_code": "PL",
    "season": 2026,
    "status": "FINISHED",
    "utc_date": datetime(2026, 10, 4, 15, 30, tzinfo=UTC),
    "home_team_id": 57,
    "away_team_id": 61,
}


def _parents(session: Session) -> None:
    session.add(Competition(code="PL", name="Premier League"))
    session.add_all([Team(id=57, name="Arsenal FC"), Team(id=61, name="Chelsea FC")])
    session.flush()


def test_every_identifier_fits_in_postgres() -> None:
    """Postgres truncates identifiers at 63 bytes and SQLite does not, so only Postgres would object.

    Worth checking here: the naming convention spells out every column of a constraint, and a
    too-long name fails the migration half way through, on one engine only.
    """
    too_long = [
        identifier
        for name, table in Base.metadata.tables.items()
        for identifier in (
            name,
            *(constraint.name for constraint in table.constraints),
            *(index.name for index in table.indexes),
        )
        if identifier and len(identifier.encode("utf-8")) > 63
    ]
    assert not too_long, too_long


def test_the_migration_creates_every_modeled_table(engine: Engine) -> None:
    actual = set(inspect(engine).get_table_names())
    assert set(Base.metadata.tables) <= actual, sorted(set(Base.metadata.tables) - actual)
    assert "alembic_version" in actual


def test_the_models_and_the_migration_agree(engine: Engine) -> None:
    """If this fails, a migration is missing. Do not fix it by editing the model."""
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    # The one expected difference: the migration stores the vector as TEXT on SQLite, while the model
    # describes it with the Embedding type decorator. Both are TEXT underneath.
    unexplained = [difference for difference in differences if "embedding" not in repr(difference)]
    assert not unexplained, "\n".join(repr(difference) for difference in unexplained)


def test_a_match_status_outside_the_enum_is_refused(session: Session) -> None:
    _parents(session)
    session.add(Match(**{**MATCH, "status": "NOT_A_STATUS"}))
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_valid_match_is_stored(session: Session) -> None:
    _parents(session)
    session.add(Match(**MATCH))
    session.flush()
    assert session.get(Match, 419823) is not None


def test_a_standings_snapshot_is_unique_per_team(session: Session) -> None:
    _parents(session)
    row = {
        "competition_code": "PL",
        "season": 2026,
        "snapshot_date": date(2026, 10, 10),
        "table_type": "TOTAL",
        "team_id": 57,
        "position": 1,
        "played": 7,
        "points": 18,
    }
    session.add(Standing(**row))
    session.flush()
    session.add(Standing(**row))
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_chunk_without_an_embedding_is_refused(session: Session) -> None:
    """`vector(768)` is the column's contract; a chunk that never got one is not knowledge."""
    session.add(
        KnowledgeChunk(
            id="00000000-0000-0000-0000-000000000001",
            source_file="policy/example.md",
            heading="Example",
            ordinal=0,
            chunk_text="A passage.",
            embedding_model="fake-embedder",
            embedding_dim=EMBEDDING_DIM,
            content_hash="0" * 64,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
