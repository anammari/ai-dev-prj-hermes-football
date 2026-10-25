"""Shared test fixtures.

The database fixtures run the *real* Alembic migration rather than `metadata.create_all`: the
migration is a deliverable, and a test that builds the schema a second way would not notice when the
two drift apart.

The API fixtures at the bottom build the same application the container serves, against the migrated
SQLite file and a deterministic embedder - no stack, no network, no model.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app import create_app
from backend.settings import BackendSettings
from db.session import create_db_engine
from db.settings import REPO_ROOT, Settings
from ingest.knowledge.embedding import FakeEmbedder
from tests import api_helpers

CORPUS = REPO_ROOT / "hermes" / "agent-knowledge"

#: The bearer token the API fixtures configure. A literal, in the test suite, is fine: it never
#: leaves the process, and `AGENTS.md` rule 6 is about the repository and the prompts.
API_TOKEN = "test-agent-token"
#: The admin token, deliberately different from the agent one: the dashboard's write path must never
#: be reachable with the token the agent holds.
ADMIN_TOKEN = "test-admin-token"


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


# ------------------------------------------------------------------------------------------------
# The API. `create_app` takes its engine and embedder as arguments for exactly this reason: the
# routes under test are the routes the container serves, on a database that costs a migration and no
# network.
# ------------------------------------------------------------------------------------------------


@pytest.fixture
def backend_settings(settings: Settings) -> BackendSettings:
    return BackendSettings(db=settings, agent_token=API_TOKEN, admin_token=ADMIN_TOKEN)


@pytest.fixture
def api_app(backend_settings: BackendSettings, engine: Engine, embedder: FakeEmbedder) -> FastAPI:
    return create_app(backend_settings, engine=engine, embedder=embedder)


@pytest.fixture
def client(api_app: FastAPI) -> Iterator[TestClient]:
    # The context manager runs the lifespan, which is where the contract, the session factory and the
    # started_at stamp are installed.
    with TestClient(api_app) as client:
        yield client


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


@pytest.fixture
def admin_auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.fixture
def seeded(session: Session, embedder: FakeEmbedder) -> api_helpers.Seeded:
    return api_helpers.seed_api(session, embedder)

