"""Tests that need the Compose stack: Postgres 16, pgvector and Ollama.

`make itest` runs these; `make test` excludes them. They are the half of M1 that a fake embedder and
SQLite cannot prove: that the pinned `vector(768)` column really is a vector, that the HNSW index
exists, that the agent's role cannot write, and that a note indexes and is retrieved through the real
`embeddinggemma:300m` running in the `ollama` service.

Prerequisites: `make up` (db + ollama, migrated) and `make models` (the ~400 MB model in the volume).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from db.models import EMBEDDING_DIM, KnowledgeChunk
from db.session import create_db_engine
from db.settings import Settings
from ingest.knowledge.embedding import OllamaEmbedder
from ingest.knowledge.indexer import index_corpus, search_knowledge

pytestmark = pytest.mark.integration

NEEDS_MODEL = "the embedding model is not in the ollama volume: run `make models` first"


@pytest.fixture(scope="module")
def stack_settings() -> Settings:
    settings = Settings.from_env()
    assert settings.is_postgres, (
        "integration tests need DATABASE_URL pointing at the Compose database, which `make itest` sets"
    )
    return settings


@pytest.fixture(scope="module")
def stack_engine(stack_settings: Settings) -> Iterator[Engine]:
    engine = create_db_engine(stack_settings)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def stack_session(stack_engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=stack_engine, expire_on_commit=False, future=True)
    with factory() as session:
        yield session


@pytest.fixture(scope="module")
def agent_engine(stack_settings: Settings) -> Iterator[Engine]:
    """A connection *as* the agent's own role, which is how the agent-facing path reads.

    The migration only gives the role a password when `AGENT_DB_PASSWORD` is set; without one it is
    created NOLOGIN and there is no login to test, so the test says so instead of pretending.
    """
    if not stack_settings.agent_db_password:
        pytest.skip("AGENT_DB_PASSWORD is unset, so agent_readonly was created NOLOGIN: no login to test")
    url = make_url(stack_settings.database_url).set(
        username=stack_settings.agent_db_role, password=stack_settings.agent_db_password
    )
    engine = create_engine(url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def embedder(stack_settings: Settings) -> Iterator[OllamaEmbedder]:
    with OllamaEmbedder(
        host=stack_settings.ollama_host,
        model=stack_settings.embedding_model,
        dim=stack_settings.embedding_dim,
    ) as embedder:
        if stack_settings.embedding_model not in embedder.available_models():
            pytest.fail(NEEDS_MODEL)
        yield embedder


def test_the_database_is_postgres_16_with_pgvector(stack_engine: Engine) -> None:
    with stack_engine.connect() as connection:
        version = connection.execute(text("select version()")).scalar_one()
        extensions = connection.execute(text("select extname from pg_extension")).scalars().all()
    assert "PostgreSQL 16" in version
    assert "vector" in extensions


def test_the_embedding_column_is_vector_768(stack_engine: Engine) -> None:
    with stack_engine.connect() as connection:
        declared = connection.execute(
            text(
                "select format_type(atttypid, atttypmod) from pg_attribute "
                "where attrelid = 'knowledge_chunks'::regclass and attname = 'embedding'"
            )
        ).scalar_one()
    assert declared == f"vector({EMBEDDING_DIM})"


def test_the_hnsw_index_exists(stack_engine: Engine) -> None:
    with stack_engine.connect() as connection:
        definitions = (
            connection.execute(text("select indexdef from pg_indexes where tablename = 'knowledge_chunks'"))
            .scalars()
            .all()
        )
    hnsw = [definition for definition in definitions if "hnsw" in definition]
    assert hnsw, definitions
    assert "vector_cosine_ops" in hnsw[0]


def test_the_provider_returns_the_pinned_width(embedder: OllamaEmbedder, stack_settings: Settings) -> None:
    """`vector(768)` is pinned in the migration (`_docs/decisions/0002`); this is the probe that keeps it honest."""
    assert embedder.probe_dimension() == EMBEDDING_DIM == stack_settings.embedding_dim


#: Things the agent's role must never be able to do, whatever the SQL is.
FORBIDDEN = (
    # A real 768-dimension literal: a wrong-width one is folded by the planner and raises a DataError
    # before the privilege check runs, which would test the type rather than the role.
    "insert into knowledge_chunks (id, source_file, heading, ordinal, chunk_text, embedding, "
    "embedding_model, embedding_dim, content_hash) values ('x', 'x', 'x', 0, 'x', "
    "array_fill(0.0::real, ARRAY[768])::vector, 'm', 768, 'h')",
    "update knowledge_chunks set heading = 'x' where false",
    "delete from knowledge_chunks where false",
    "create table agent_may_not (id integer)",
    "alter table matches add column sneaky integer",
    "drop table knowledge_chunks",
    "create extension if not exists hstore",
)


def test_the_agent_role_may_read_but_not_write(agent_engine: Engine, stack_settings: Settings) -> None:
    """`R-F2.4` / AGENTS.md rule 4, checked against the real privileges rather than the intent.

    Each statement gets its own connection on purpose: `SET ROLE`, were it used here, is undone by a
    rollback, so a failed statement would silently hand the next one back the owner's rights.
    """
    with agent_engine.connect() as connection:
        assert connection.execute(text("select current_user")).scalar_one() == stack_settings.agent_db_role
        assert connection.execute(text("select count(*) from knowledge_chunks")).scalar() is not None
        assert connection.execute(text("select count(*) from matches")).scalar() is not None

    for statement in FORBIDDEN:
        with agent_engine.connect() as connection, pytest.raises(ProgrammingError):
            connection.execute(text(statement))


def test_a_note_indexes_and_is_retrieved_through_ollama(
    stack_session: Session, stack_settings: Settings, embedder: OllamaEmbedder
) -> None:
    """The M1 acceptance criterion, with the real model on the real database."""
    report = index_corpus(stack_session, stack_settings, embedder=embedder)
    stack_session.commit()
    assert report.chunks_written > 0 or report.unchanged, report.summary()

    stored = list(stack_session.scalars(select(KnowledgeChunk)))
    assert stored, "the corpus indexed to nothing"
    assert {chunk.embedding_model for chunk in stored} == {stack_settings.embedding_model}
    assert {chunk.embedding_dim for chunk in stored} == {EMBEDDING_DIM}

    hits = search_knowledge(stack_session, embedder, "how old is the football data, and is it live?", limit=3)
    assert hits, "the corpus did not answer a question it covers"
    assert hits[0][0].source_file == "policy/free-tier-delay-and-coverage.md", [
        (chunk.source_file, round(score, 3)) for chunk, score in hits
    ]


def test_indexing_twice_on_postgres_writes_nothing(
    stack_session: Session, stack_settings: Settings, embedder: OllamaEmbedder
) -> None:
    index_corpus(stack_session, stack_settings, embedder=embedder)
    stack_session.commit()
    second = index_corpus(stack_session, stack_settings, embedder=embedder)
    stack_session.commit()
    assert second.chunks_written == 0
    assert second.indexed == []
