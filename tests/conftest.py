"""Shared test fixtures.

The database fixtures run the *real* Alembic migration rather than `metadata.create_all`: the
migration is a deliverable, and a test that builds the schema a second way would not notice when the
two drift apart.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from db.session import create_db_engine
from db.settings import REPO_ROOT, Settings
from ingest.knowledge.embedding import FakeEmbedder

CORPUS = REPO_ROOT / "hermes" / "agent-knowledge"


def alembic_config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
def knowledge_dir() -> Path:
    """The corpus in the working tree, not the one baked into an image."""
    return CORPUS


@pytest.fixture
def corpus_copy(tmp_path: Path) -> Path:
    """A writable copy of the corpus, for tests that must break something."""
    target = tmp_path / "corpus"
    shutil.copytree(CORPUS, target)
    return target


@pytest.fixture
def settings(tmp_path: Path, knowledge_dir: Path) -> Settings:
    """SQLite, no network, embedding model name that cannot reach out to Ollama."""
    return replace(
        Settings.from_env({}),
        database_url=f"sqlite+pysqlite:///{tmp_path / 'hermes.db'}",
        knowledge_dir=knowledge_dir,
        embedding_model="fake-embedder",
    )


@pytest.fixture
def migrated_url(settings: Settings) -> str:
    command.upgrade(alembic_config(settings.database_url), "head")
    return settings.database_url


@pytest.fixture
def engine(migrated_url: str, settings: Settings) -> Iterator[Engine]:
    engine = create_db_engine(settings)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as session:
        yield session


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()
