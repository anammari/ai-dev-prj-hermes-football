"""The one write, on real Postgres, through the role the dashboard uses.

Everything here is falsifiable only on Postgres: SQLite has no roles, so it cannot show that
`agent_admin` may update the two review columns and nothing else. The test creates its own turn row,
reviews it through the API, proves the column-level grant holds, and deletes only its own row in
teardown - the retained volume's real turns are never read or modified.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from backend.app import create_app
from backend.db import admin_database_url, create_admin_engine, create_read_engine
from backend.settings import BackendSettings
from db.session import create_db_engine
from db.settings import Settings
from ingest.knowledge.embedding import OllamaEmbedder

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def stack_settings() -> Settings:
    settings = Settings.from_env()
    assert settings.is_postgres, "integration tests need DATABASE_URL pointing at the Compose database"
    return settings


@pytest.fixture(scope="module")
def backend_settings(stack_settings: Settings) -> BackendSettings:
    settings = BackendSettings.from_env()
    assert settings.agent_token, "API_AGENT_TOKEN is unset"
    if not settings.admin_token:
        pytest.skip("API_ADMIN_TOKEN is unset: the review write is disabled in this deployment")
    return settings


@pytest.fixture(scope="module")
def owner_engine(stack_settings: Settings) -> Engine:
    engine = create_db_engine(stack_settings)
    yield engine
    engine.dispose()


@pytest.fixture
def turn(owner_engine: Engine) -> Iterator[str]:
    """A throwaway turn row: created here, deleted here, never a real user's answer."""
    turn_id = str(uuid.uuid4())
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "insert into agent_turns (id, user_message, answer, grounded, review_status, route, route_source) "
                "values (:id, :message, :answer, true, 'unreviewed', 'tool', 'model')"
            ),
            {
                "id": turn_id,
                "message": "integration fixture: where are Arsenal?",
                "answer": "integration fixture answer",
            },
        )
    yield turn_id
    with owner_engine.begin() as connection:
        connection.execute(text("delete from agent_turns where id = :id"), {"id": turn_id})


@pytest.fixture(scope="module")
def api(stack_settings: Settings, backend_settings: BackendSettings) -> TestClient:
    embedder = OllamaEmbedder(
        host=stack_settings.ollama_host,
        model=stack_settings.embedding_model,
        dim=stack_settings.embedding_dim,
    )
    app = create_app(backend_settings, engine=create_read_engine(stack_settings), embedder=embedder)
    with TestClient(app) as client:
        yield client
    embedder.close()


def test_the_admin_role_can_review_and_nothing_else(stack_settings: Settings, turn: str) -> None:
    """The grant is the bound: UPDATE on two columns works, UPDATE on the answer does not."""
    assert admin_database_url(stack_settings) != stack_settings.database_url, (
        "AGENT_ADMIN_DB_PASSWORD is unset: the review role was created NOLOGIN and the write path "
        "would fall back to the owner URL"
    )
    engine = create_admin_engine(stack_settings)
    try:
        with engine.begin() as connection:
            user = connection.execute(text("select current_user")).scalar_one()
            assert user == stack_settings.admin_db_role
            connection.execute(
                text("update agent_turns set review_status = 'flagged' where id = :id"), {"id": turn}
            )
            # The grant is column-level: the same role that just wrote the review column may not
            # rewrite the answer it is reviewing. SQLAlchemy wraps the driver error, so the assertion
            # is on the message rather than on sqlite/postgres exception classes.
            with pytest.raises(DBAPIError) as denied:
                connection.execute(
                    text("update agent_turns set answer = 'rewritten' where id = :id"), {"id": turn}
                )
            assert "permission denied" in str(denied.value).lower()
    finally:
        engine.dispose()


def test_the_review_endpoint_writes_through_the_admin_role(
    api: TestClient, backend_settings: BackendSettings, turn: str
) -> None:
    response = api.patch(
        f"/admin/agent-turns/{turn}/review",
        json={"reviewStatus": "wrong", "note": "checked against the tool result"},
        headers={"Authorization": f"Bearer {backend_settings.admin_token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["review_status"] == "wrong"
    assert body["review_note"] == "checked against the tool result"

    read_back = api.get(
        "/agent/turns",
        params={"reviewStatus": "wrong"},
        headers={"Authorization": f"Bearer {backend_settings.agent_token}"},
    )
    assert any(row["id"] == turn for row in read_back.json()["data"])


def test_the_agent_token_cannot_review(
    api: TestClient, backend_settings: BackendSettings, turn: str
) -> None:
    response = api.patch(
        f"/admin/agent-turns/{turn}/review",
        json={"reviewStatus": "correct"},
        headers={"Authorization": f"Bearer {backend_settings.agent_token}"},
    )
    assert response.status_code == 401
