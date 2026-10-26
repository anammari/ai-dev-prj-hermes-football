"""The M3 acceptance test: the API served from the Compose stack, on real Postgres and pgvector.

`make itest` runs this against the retained stack; `make itest-isolated` against a throwaway Compose
project. What only this file can prove:

* the request path really logs in as `agent_readonly` (`AGENTS.md` rule 4) instead of as the owner,
  which SQLite has no way to express;
* the SQL that matters on Postgres is the SQL that runs there - `jsonb` scopes on `ingest_runs`,
  `vector(768)` cosine ranking for `/search/knowledge`, `numeric` scores, timezone-aware timestamps -
  and every response still validates against `openapi.yaml`;
* the container that `make up` starts answers its own healthcheck, refuses an unauthenticated request,
  and serves the reviewed contract file byte for byte.

This file never writes to the database. Tests that need ingested rows say so and skip: an empty
throwaway volume should report "nothing to read", not fail, and no test here invents rows in the
retained volume or deletes real ones.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.app import create_app
from backend.db import agent_database_url, create_read_engine, read_only
from backend.routers import admin
from backend.settings import BackendSettings
from db.models import Competition, EvalRun, Match, Team
from db.session import create_db_engine
from db.settings import Settings
from ingest.knowledge.embedding import OllamaEmbedder
from tests import api_helpers
from tests.api_helpers import validate

pytestmark = pytest.mark.integration

NEEDS_MODEL = "the embedding model is not in the ollama volume: run `make models` first"
NEEDS_DATA = (
    "this database holds no ingested matches: run `make ingest` (needs a real UPSTREAM_API_KEY), "
    "or point the stack at the retained volume with `make itest`"
)

#: Where the running `backend` container answers. `make itest-isolated` sets this to the service name.
BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://localhost:8000")

#: The operations this sweep must cover. Written out here as well as derived in the unit suite, so that
#: a shrinking route table changes this number instead of silently skipping operations.
IMPLEMENTED_GET = [
    operation_id
    for operation_id, (method, _path, _node) in api_helpers.operations().items()
    if method == "GET" and operation_id not in admin.UNIMPLEMENTED
]

#: ...minus the two that serve a document rather than JSON: the contract file itself and the Swagger UI
#: page. They are checked separately, by comparing bytes and by asking for the page.
DOCUMENT_OPERATIONS = ("getOpenApiDocument", "getSwaggerUi")


@pytest.fixture(scope="module")
def stack_settings() -> Settings:
    settings = Settings.from_env()
    assert settings.is_postgres, (
        "integration tests need DATABASE_URL pointing at the Compose database, which `make itest` sets"
    )
    return settings


@pytest.fixture(scope="module")
def backend_settings(stack_settings: Settings) -> BackendSettings:
    settings = BackendSettings.from_env()
    assert settings.agent_token, "API_AGENT_TOKEN is unset: the container would refuse every request"
    return settings


@pytest.fixture(scope="module")
def stack_engine(stack_settings: Settings) -> Iterator[Engine]:
    engine = create_db_engine(stack_settings)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def stack_session(stack_engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=stack_engine, expire_on_commit=False, future=True)() as session:
        yield session


@pytest.fixture(scope="module")
def embedder(stack_settings: Settings) -> Iterator[OllamaEmbedder]:
    with OllamaEmbedder(
        host=stack_settings.ollama_host,
        model=stack_settings.embedding_model,
        dim=stack_settings.embedding_dim,
    ) as instance:
        if stack_settings.embedding_model not in instance.available_models():
            pytest.fail(NEEDS_MODEL)
        yield instance


@pytest.fixture(scope="module")
def api(
    stack_settings: Settings, backend_settings: BackendSettings, embedder: OllamaEmbedder
) -> Iterator[TestClient]:
    """The app against the real database, so the SQL under test is Postgres's."""
    app = create_app(backend_settings, engine=create_read_engine(stack_settings), embedder=embedder)
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def auth(backend_settings: BackendSettings) -> dict[str, str]:
    return {"Authorization": f"Bearer {backend_settings.agent_token}"}


@pytest.fixture(scope="module")
def ids(stack_session: Session) -> dict[str, int | str]:
    """A real id for every parameter the contract takes, read from the volume rather than invented."""
    match = stack_session.scalar(select(Match).order_by(Match.utc_date.desc()).limit(1))
    team = stack_session.scalar(select(Team).order_by(Team.id).limit(1))
    if match is None or team is None:
        pytest.skip(NEEDS_DATA)
    return {
        "match": match.id,
        "team": team.id,
        "competition": match.competition_code,
        "season": match.season,
    }


@pytest.fixture(scope="module")
def eval_run_id(stack_session: Session) -> str | None:
    """The newest eval run in this volume, if `make eval` has ever run against it.

    The contract sweep needs a real id and this file must not invent rows: an empty scoreboard is a
    legitimate state on a fresh volume, and the sweep says so rather than skipping silently.
    """
    return stack_session.scalar(select(EvalRun.id).order_by(EvalRun.started_at.desc()).limit(1))


# ------------------------------------------------------------------------------------------------
# Rule 4, where it is falsifiable
# ------------------------------------------------------------------------------------------------


def test_the_read_engine_logs_in_as_the_read_only_role(stack_settings: Settings) -> None:
    """Not "the code looks read-only" but "Postgres says who is connected"."""
    if not stack_settings.agent_db_password:
        pytest.skip("AGENT_DB_PASSWORD is unset, so agent_readonly was created NOLOGIN: no login to test")
    assert read_only(stack_settings) is True
    url = make_url(agent_database_url(stack_settings))
    assert url.username == stack_settings.agent_db_role
    assert url.password not in (None, "")

    engine = create_read_engine(stack_settings)
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(text("select current_user")).scalar_one() == stack_settings.agent_db_role
            )
    finally:
        engine.dispose()


def test_the_read_only_role_may_not_write_through_the_apis_own_engine(stack_settings: Settings) -> None:
    """The engine the request path holds is the one probed, so this covers the connection the API
    actually uses rather than a role of the same name somewhere else."""
    if not stack_settings.agent_db_password:
        pytest.skip("AGENT_DB_PASSWORD is unset, so agent_readonly was created NOLOGIN: no login to test")
    from sqlalchemy.exc import ProgrammingError

    engine = create_read_engine(stack_settings)
    try:
        for statement in (
            "update matches set status = 'X' where false",
            "delete from ingest_runs where false",
            "create table api_may_not (id integer)",
        ):
            with engine.connect() as connection, pytest.raises(ProgrammingError):
                connection.execute(text(statement))
    finally:
        engine.dispose()


# ------------------------------------------------------------------------------------------------
# Postgres-specific shapes
# ------------------------------------------------------------------------------------------------


def test_the_ledger_scope_column_is_json_and_reads_back_as_a_list(stack_session: Session, api, auth) -> None:
    """`ingest_runs.competitions` is a JSON column on both dialects (`sa.JSON`, so the same model works
    on SQLite), and every non-null value is an *array*: the API serialises it straight through, and the
    score-delay poll writes a run whose scope is the empty array.

    The first version of this test asserted `jsonb` and failed against the retained volume, which is
    `json`. That was the test's assumption, not the code's bug - and it is the reason the assertion now
    describes the property the API needs (`json_typeof = 'array'`) rather than one spelling of the
    storage type."""
    declared = stack_session.execute(
        text(
            "select format_type(atttypid, atttypmod) from pg_attribute "
            "where attrelid = 'ingest_runs'::regclass and attname = 'competitions'"
        )
    ).scalar_one()
    assert declared in ("json", "jsonb"), declared

    rows, arrays = stack_session.execute(
        text(
            "select count(*), count(*) filter (where json_typeof(competitions) = 'array') "
            "from ingest_runs where competitions is not null"
        )
    ).one()
    assert rows == arrays, f"{rows - arrays} scope values are not JSON arrays"

    # A run that refreshed nothing is stored as SQL NULL (the score-delay polls) or as an empty
    # array, and the API serves both as `[]` - the contract's `competitions` is a non-nullable array,
    # so a client never has to tell "no scope" from "empty scope" to know that nothing was refreshed.
    unscoped = stack_session.scalar(
        text(
            "select count(*) from ingest_runs where competitions is null "
            "or json_array_length(competitions) = 0"
        )
    )
    body = api.get("/meta/ingest-runs", headers=auth).json()
    assert all(isinstance(run["competitions"], list) for run in body["data"])
    assert sum(1 for run in body["data"] if run["competitions"] == []) == unscoped, (
        "every unscoped run is served as an empty list, never as null"
    )


def test_the_knowledge_search_really_uses_pgvector(
    stack_session: Session, stack_settings: Settings, backend_settings: BackendSettings, embedder: OllamaEmbedder
) -> None:
    """The similarity search is `embedding <=> query` on a real `vector(768)` column with the HNSW
    index behind it. The SQLite path computes cosine in Python and would keep passing if this broke."""
    chunks = stack_session.scalar(text("select count(*) from knowledge_chunks")) or 0
    if not chunks:
        pytest.skip("no chunks indexed on this volume: run `make index-notes`")

    app = create_app(backend_settings, engine=create_read_engine(stack_settings), embedder=embedder)
    with TestClient(app) as client:
        body = client.get(
            "/search/knowledge",
            params={"q": "how old is the football data, and is it live?", "minScore": 0},
            headers={"Authorization": f"Bearer {backend_settings.agent_token}"},
        ).json()
    hits = body["data"]
    assert hits, "the curated question covers a note that is indexed"
    assert hits[0]["source_file"] == "policy/free-tier-delay-and-coverage.md", [
        (hit["source_file"], round(hit["score"], 4)) for hit in hits
    ]
    assert hits[0]["score"] >= hits[-1]["score"], "ranked, best first"


def test_the_database_version_column_is_what_health_quotes(stack_session: Session, api) -> None:
    """`/health` reads `alembic_version`, the same table the migration writes. If a migration renames
    it, the probe goes to `unknown` and this test says why."""
    revision = stack_session.execute(text("select version_num from alembic_version")).scalar_one()
    body = api.get("/health").json()
    assert body["status"] == "ok"
    assert body["db"]["schema_revision"] == revision


# ------------------------------------------------------------------------------------------------
# Every implemented GET operation, against real rows
# ------------------------------------------------------------------------------------------------


def real_ids(ids: dict[str, int | str]) -> dict:
    """The contract's example ids, replaced by ids that exist on this volume.

    These go in as `request_for_with` *overrides*, not as a patch on the finished URL: `matchId` and
    `code` are path parameters, and the helper has already substituted the contract's own examples
    into the template by the time it returns. Passing the example `/matches/419823` to a volume whose
    matches start at 560912 is what made this sweep fail the first time it was pointed at real data."""
    return {
        "matchId": ids["match"],
        "teamId": ids["team"],
        "teamA": ids["team"],
        "code": ids["competition"],
        "season": ids["season"],
    }


def test_every_implemented_operation_answers_from_the_real_volume(api, auth, ids, eval_run_id) -> None:
    """The contract sweep again, with real Postgres types behind it: `numeric` scores, `jsonb` scopes,
    timezone-aware dates, `vector(768)`. Each response is validated against the schema its operation
    declares, so drift from `openapi.yaml` fails here too - and a query that only works on SQLite fails
    here and nowhere else.

    `getEvalRun` is the one operation whose data may legitimately be absent: a volume where `make eval`
    has never run has no scoreboard, and this file does not invent a row to fill it. When a run exists,
    the sweep covers it like anything else.
    """
    covered = 0
    absent: list[str] = []
    for operation_id, (method, path, node) in api_helpers.operations().items():
        if method != "GET" or operation_id in DOCUMENT_OPERATIONS:
            continue
        overrides = {**api_helpers.SWEEP_OVERRIDES.get(operation_id, {}), **real_ids(ids)}
        if operation_id == "getEvalRun":
            if eval_run_id is None:
                absent.append(operation_id)
                continue
            overrides["runId"] = eval_run_id
        _method, path, params = api_helpers.request_for_with(operation_id, overrides=overrides)
        response = api.request(method, path, params=params, headers=auth)
        assert response.status_code == 200, (
            f"{operation_id} {path} {params}: {response.status_code} {response.text[:200]}"
        )
        if "json" in response.headers["content-type"]:
            schema = node["responses"]["200"]["content"]["application/json"]["schema"]
            validate(response.json(), schema, where=operation_id)
        covered += 1
    expected = [name for name in IMPLEMENTED_GET if name not in DOCUMENT_OPERATIONS]
    assert absent in ([], ["getEvalRun"]), absent
    assert covered == len(expected) - len(absent), (
        f"the sweep covered {covered} of {len(expected) - len(absent)} JSON operations"
    )


def test_a_real_match_round_trips_the_providers_own_fields(api, auth, ids) -> None:
    match = api.get(f"/matches/{ids['match']}", headers=auth).json()["data"]
    assert match["competition"]["code"] == ids["competition"]
    assert match["season"] == ids["season"]
    assert match["home_team"]["id"] and match["away_team"]["id"]
    if match["status"] in ("FINISHED", "AWARDED"):
        assert match["score"]["full_time"]["home"] is not None
        # `last_updated` is the provider's stamp, never ours: it cannot be in the future.
        assert datetime.fromisoformat(match["last_updated"].replace("Z", "+00:00")) <= datetime.now(UTC)


def test_the_catalog_the_contract_enum_and_the_freshness_report_agree(
    stack_session: Session, api, auth
) -> None:
    """Three statements of the same fact that would otherwise drift apart in silence: the rows in
    `competitions`, the codes `openapi.yaml` accepts, and the codes `/meta/freshness` reports.

    The enum is the contract's way of saying "the set this deployment can ingest", so an ingested
    competition outside it is the finding this test exists for: it means the upstream plan grew and the
    contract needs the same one-line change ingestion already made.
    """
    ingested = set(stack_session.scalars(select(Competition.code)).all())
    allowed = set(api_helpers.resolve(api_helpers.SCHEMAS["CompetitionCode"])["enum"])
    assert ingested <= allowed, f"ingested but rejected by the contract's enum: {sorted(ingested - allowed)}"

    listed = [row["code"] for row in api.get("/competitions", headers=auth).json()["data"]]
    reported = [row["code"] for row in api.get("/meta/freshness", headers=auth).json()["competitions"]]
    assert listed == reported
    assert set(listed) == ingested, "a competition in the table but not in the API is invisible to the agent"


def test_freshness_counts_the_rows_it_claims(stack_session: Session, api, auth) -> None:
    """`rows` is the checkable half of a freshness claim: the number the API reports for a competition
    must be the number of rows the table holds for it."""
    report = api.get("/meta/freshness", headers=auth).json()
    assert report["overall_status"] in {"fresh", "stale", "unknown"}
    for row in report["competitions"]:
        stored = stack_session.scalar(
            select(func.count()).select_from(Match).where(Match.competition_code == row["code"])
        )
        assert row["rows"]["matches"] == stored, f"{row['code']}: {row['rows']} against {stored} stored"


def test_the_served_contract_is_byte_for_byte_the_reviewed_file(api) -> None:
    """The point of serving the file rather than a generated document: a reviewer can diff them."""
    from backend.settings import DEFAULT_CONTRACT_PATH

    assert api.get("/openapi.yaml").text == DEFAULT_CONTRACT_PATH.read_text(encoding="utf-8")
    assert api.get("/openapi.json").status_code == 404


# ------------------------------------------------------------------------------------------------
# The container `make up` starts
# ------------------------------------------------------------------------------------------------


def test_the_container_answers_its_own_healthcheck() -> None:
    """`make up` waits on this exact request, so it also covers the Compose wiring (image, command,
    published port) rather than only the app object."""
    try:
        response = httpx.get(f"{BASE_URL}/health", timeout=10)
    except httpx.HTTPError as error:
        pytest.fail(
            f"no backend at {BASE_URL} ({error}): `make up` starts it, and `make itest-isolated` sets "
            "BACKEND_BASE_URL to the Compose service name"
        )
    assert response.status_code == 200
    assert response.json()["status"] in {"ok", "degraded"}


def test_the_container_refuses_an_unauthenticated_request() -> None:
    """The token travels with the deployment; the guard is on in the container as it is in tests."""
    response = httpx.get(f"{BASE_URL}/competitions", timeout=10)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_the_container_serves_the_token_the_deployment_configured(backend_settings: BackendSettings) -> None:
    response = httpx.get(
        f"{BASE_URL}/competitions",
        headers={"Authorization": f"Bearer {backend_settings.agent_token}"},
        timeout=20,
    )
    assert response.status_code == 200
    assert "data" in response.json()
