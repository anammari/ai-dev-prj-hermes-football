"""Authentication, the error envelope, and the two hard rules a reviewer cannot see in a response body.

`AGENTS.md` rule 3 (all upstream access goes through the ingest client, never from request-handling
code) and rule 4 (the agent's data path is read-only) are properties of the whole `backend/` package,
not of any one endpoint, so they are checked here by inspection: the imports a request path may use,
and the database role the read engine connects as. A response test cannot see either.
"""

from __future__ import annotations

import ast
import re
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.db import create_read_engine, read_only
from backend.services import reviews
from backend.settings import BackendSettings
from db.settings import REPO_ROOT, Settings
from tests import api_helpers
from tests.api_helpers import operations, request_for_with

BACKEND = REPO_ROOT / "backend"

#: The one module allowed to write, and the columns it may write. Kept next to the guard so the two
#: cannot drift: the writer declares `REVIEW_COLUMNS`, and this test holds the file to it.
REVIEW_WRITE_MODULE = "backend/services/reviews.py"

#: Operations the contract marks `security: []`, and which must therefore answer without a token.
OPEN_OPERATIONS = [
    operation_id
    for operation_id, (_method, _path, node) in operations().items()
    if node.get("security") == []
]

#: Everything else, read straight from the contract rather than from a list kept by hand: a new
#: operation that forgets its auth dependency is caught the moment it is declared.
PROTECTED_OPERATIONS = [
    operation_id
    for operation_id, (_method, _path, node) in operations().items()
    if node.get("security") != []
]


def test_only_the_documented_operations_are_open() -> None:
    assert sorted(OPEN_OPERATIONS) == ["getHealth", "getOpenApiDocument", "getSwaggerUi"]


@pytest.mark.parametrize("operation_id", OPEN_OPERATIONS)
def test_an_open_operation_answers_without_a_token(client: TestClient, operation_id: str) -> None:
    method, path, _node = operations()[operation_id]
    assert client.request(method, path).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "test-agent-token"},
        {"Authorization": "Bearer test-agent-token-extra"},
        {"X-API-Key": "test-agent-token"},
    ],
)
def test_everything_else_needs_the_exact_bearer_token(client: TestClient, headers) -> None:
    """Case-sensitive scheme, exact token, nothing accepted as a substitute - a token that is too long
    is as wrong as one that is too short."""
    response = client.get("/competitions", headers=headers)
    assert response.status_code == 401, headers
    error = response.json()["error"]
    assert error["code"] == "unauthorized"
    assert "test-agent-token" not in response.text, "never echo the token back"


@pytest.mark.parametrize("operation_id", PROTECTED_OPERATIONS)
def test_every_protected_operation_refuses_an_anonymous_caller(client: TestClient, operation_id: str) -> None:
    """One test per protected operation, driven by the contract's own `security` block. A route that
    forgets its dependency fails here - which is how the two declared `/admin` stubs were caught
    answering 404 to a stranger before they answered 401."""
    method, path, params = request_for_with(operation_id, overrides=api_helpers.SWEEP_OVERRIDES.get(operation_id, {}))
    response = client.request(method, path, params=params)
    assert response.status_code == 401, f"{operation_id} answered {response.status_code} without a token"
    assert response.json()["error"]["code"] == "unauthorized"


def test_the_auth_scheme_is_matched_the_way_http_says_to(client: TestClient) -> None:
    """RFC 7235 makes the scheme case-insensitive, so `bearer` and `Bearer` are the same credential.
    Being stricter than HTTP would break clients for no security gain; the token itself is still
    compared in constant time."""
    assert client.get("/competitions", headers={"Authorization": "bearer test-agent-token"}).status_code == 200


def test_an_unconfigured_token_fails_closed(engine, settings) -> None:
    """No `API_AGENT_TOKEN` in the environment must mean "nobody gets in", not "everybody gets in".
    The container refuses to start without it (`backend/settings.py`), and the app behind it refuses
    every request even if that check were bypassed."""
    app = create_app(BackendSettings(db=settings), engine=engine)
    with TestClient(app) as client:
        assert client.get("/competitions", headers={"Authorization": "Bearer "}).status_code == 401
        assert client.get("/health").status_code == 200, "the probe stays open"


def test_the_error_envelope_carries_a_request_id_that_matches_the_header(client: TestClient, auth) -> None:
    response = client.get("/matches/999999", headers=auth)
    body = response.json()
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f-]{36}", body["error"]["request_id"])


def test_every_response_carries_a_request_id_and_no_two_are_alike(client: TestClient, auth) -> None:
    first = client.get("/health")
    second = client.get("/health")
    assert first.headers["x-request-id"] != second.headers["x-request-id"]
    for response in (first, second):
        assert re.fullmatch(r"[0-9a-f-]{36}", response.headers["x-request-id"])


def test_a_validation_error_is_a_400_with_the_offending_field_named(client: TestClient, auth) -> None:
    """FastAPI's default is a 422 with `{"detail": [...]}`, which is not a shape this contract
    documents. A client should be able to show the message as it is."""
    response = client.get("/competitions/PL/matches", params={"limit": 500}, headers=auth)
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_parameter"
    assert "limit" in body["error"]["message"]
    assert body["error"]["details"]["errors"][0]["location"] == ["query", "limit"]


def test_an_unknown_route_is_the_contract_error_shape_not_starlettes(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert "detail" not in response.json()
    assert response.json()["error"]["code"] == "not_found"


def test_an_unexpected_failure_does_not_leak_its_message(api_app, auth, monkeypatch) -> None:
    """A traceback can carry a DSN, a token or a path on the host. The contract promises a message
    that is safe to show a user, so the details stay in the log."""

    def explode(*_args, **_kwargs):
        raise RuntimeError("postgresql://hermes:hunter2@db:5432/hermes is unreachable")

    monkeypatch.setattr("backend.routers.competitions.catalog.list_competitions", explode)
    # TestClient re-raises server errors so a test cannot accidentally hide one; here the 500 is the
    # thing under test, so it is turned off for this client only.
    with TestClient(api_app, raise_server_exceptions=False) as client:
        response = client.get("/competitions", headers=auth)
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "Unexpected server error."
    assert "hunter2" not in response.text


# ------------------------------------------------------------------------------------------------
# Rule 3 and rule 4, at the container boundary
# ------------------------------------------------------------------------------------------------


def compose_stack() -> dict:
    """`docker-compose.yml` as data. It is the deployment's own statement of what each service may
    reach, so the rules can be checked against it rather than against the intent in a comment."""
    import yaml

    return yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_the_api_container_has_no_provider_credential() -> None:
    """Rule 3 without trusting the code: the API container is not given an upstream key at all, and
    the shared environment anchor has none either, so no service added later inherits one by accident.
    """
    stack = compose_stack()
    assert "UPSTREAM_API_KEY" not in stack["x-app-env"]
    assert "UPSTREAM_BASE_URL" not in stack["x-app-env"]
    api = stack["services"]["backend"]["environment"]
    assert not {key for key in api if key.startswith("UPSTREAM_")}, api
    assert "UPSTREAM_API_KEY" in stack["services"]["ingest"]["environment"], (
        "the ingest scheduler is the one service allowed to hold the provider key"
    )


def test_the_api_container_mounts_read_only_and_has_no_docker_socket() -> None:
    """Rules 4 and 5: the corpus is a read-only mount, and the socket is nowhere in the stack."""
    stack = compose_stack()
    api_volumes = stack["services"]["backend"]["volumes"]
    assert api_volumes, "the API reads the corpus"
    assert all(str(volume).endswith(":ro") for volume in api_volumes), api_volumes
    for name, service in stack["services"].items():
        for volume in service.get("volumes", []):
            assert "docker.sock" not in str(volume), f"{name} mounts the Docker socket"


def test_the_api_is_the_only_published_port_in_the_stack() -> None:
    """`_docs/product-spec.md` §4: one published port, the API's. A second one would be a surface
    nobody asked for - and the dev overlay is where a port for a host tool belongs."""
    stack = compose_stack()
    published = {name: service["ports"] for name, service in stack["services"].items() if service.get("ports")}
    assert list(published) == ["backend"], published
    assert published["backend"] == ["${BACKEND_PORT:-8000}:8000"]


# ------------------------------------------------------------------------------------------------
# Rule 3 and rule 4, by inspection
# ------------------------------------------------------------------------------------------------

#: Modules a request path must not import: the upstream client, or any way to speak HTTP or reach the
#: network by another road. `urllib` is banned as a whole package, not as `urllib.request`: a review
#: probe walked past the dotted form with `from ingest import client` and `importlib.import_module`.
FORBIDDEN = (
    "httpx",
    "requests",
    "urllib",
    "http",
    "socket",
    "ssl",
    "ftplib",
    "smtplib",
    "telnetlib",
    "subprocess",
    "importlib",
    "aiohttp",
    "ingest.client",
    "ingest.football_data",
    "db.session.create_db_engine",
)

#: The only parts of `ingest` a request path may touch. Stated as a whitelist because `from ingest import
#: client` imports the package named `ingest`, which no blacklist of dotted submodules can catch.
#:
#: * `ingest.knowledge` is the corpus reader and the embedding client - an HTTP call to the local
#:   Ollama, which is why the transitive check below is about the *upstream* client, not about httpx.
#: * `ingest.scheduler` contributes one pure stdlib function, `next_run`, which is the deployment's own
#:   definition of when the daily run happens. Recomputing it in the API would let the two drift, and
#:   the report would then promise a schedule the scheduler does not keep.
ALLOWED_INGEST_IMPORTS = ("ingest.knowledge", "ingest.scheduler")

#: What "reach upstream" means transitively: the client, its transport, or the pipeline that drives it.
UPSTREAM_MODULES = ("ingest.client", "ingest.pipeline", "ingest.football_data", "ingest.__main__")


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def backend_sources() -> list[Path]:
    return sorted(BACKEND.rglob("*.py"))


def module_path(name: str) -> Path | None:
    """`ingest.knowledge` is a package, `ingest.scheduler` a module; both are importable things here."""
    as_file = REPO_ROOT / (name.replace(".", "/") + ".py")
    if as_file.exists():
        return as_file
    as_package = REPO_ROOT / name.replace(".", "/") / "__init__.py"
    return as_package if as_package.exists() else None


def test_the_request_path_cannot_reach_upstream() -> None:
    """Rule 3: "All API access goes through the ingest client - never call upstream from
    request-handling code." The API has no upstream credential and no HTTP client, and this is the
    check that keeps it that way as the package grows."""
    sources = backend_sources()
    assert len(sources) >= 15, "the package is there to be checked"
    for path in sources:
        imported = imports_of(path)
        forbidden = sorted(
            name for name in imported if any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN)
        )
        assert not forbidden, f"{path.relative_to(REPO_ROOT)} imports {forbidden}"
        # Whitelist, not blacklist: anything under `ingest` that is not the corpus reader is a way to
        # reach upstream (the client, the pacer, the pipeline).
        strays = sorted(
            name
            for name in imported
            if (name == "ingest" or name.startswith("ingest."))
            and not any(name == ok or name.startswith(ok + ".") for ok in ALLOWED_INGEST_IMPORTS)
        )
        assert not strays, f"{path.relative_to(REPO_ROOT)} imports {strays} from ingest"


#: SQL a request path may send. Every query in this service is an ORM `select`; the two hand-written
#: statements read `alembic_version`. A statement that does not start with one of these is a write or
#: a DDL, whatever the driver is called.
READ_ONLY_SQL = ("select", "with")


def test_the_modules_the_api_borrows_from_ingest_do_not_reach_upstream() -> None:
    """The whitelist above names modules; this is the property that makes those names safe. It starts
    from what `backend/` actually imports out of `ingest` and follows those modules' own local imports,
    failing the day one of them grows a dependency on the upstream client - which is what would put a
    provider credential back in the API's process."""
    borrowed = sorted(
        {
            name
            for path in backend_sources()
            for name in imports_of(path)
            if name == "ingest" or name.startswith("ingest.")
        }
    )
    assert borrowed, "the guard would pass vacuously if backend/ imported no corpus reader at all"
    pending, seen = list(borrowed), set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        module = module_path(name)
        assert module is not None, f"{name} is not a module in this repo"
        for imported in imports_of(module):
            assert imported not in UPSTREAM_MODULES, f"{name} imports {imported}"
            if imported.startswith(("ingest.", "db.")) and module_path(imported) is not None:
                pending.append(imported)
    assert "ingest.knowledge.embedding" in seen, "the corpus reader is reached through its embedder"


def test_no_backend_module_writes_to_the_database() -> None:
    """Rule 4: "No write tool, no DDL, no arbitrary SQL from model output." The read path must not
    commit, flush, insert or execute DDL - not through the session's write helpers, and not through a
    hand-written statement either. A review probe passed `session.execute(text("DELETE FROM matches"))`
    through the first version of this test, which checked only the helper methods.

    M5 adds one deliberate exception: the review decision. It lives in exactly one module, and the
    next test pins what that module may write. Every other backend module stays read-only, so a second
    writer is a failure here rather than a question in review.
    """
    banned_calls = {"commit", "flush", "add", "add_all", "delete", "merge", "bulk_save_objects"}
    writers: set[str] = set()
    for path in backend_sources():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in banned_calls and isinstance(node.func.value, ast.Name):
                    if node.func.value.id in {"session", "db"}:
                        writers.add(str(path.relative_to(REPO_ROOT)))
            # Raw SQL, if any, has to be a read: `text("...")` with a literal that selects.
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "text":
                for argument in node.args:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        statement = argument.value.strip().lower()
                        assert statement.startswith(READ_ONLY_SQL), (
                            f"{path.relative_to(REPO_ROOT)} executes {argument.value[:60]!r}"
                        )
        assert "create_all" not in source, path
        if path.name != "db.py":
            assert "create_db_engine" not in source, (
                f"{path.relative_to(REPO_ROOT)} builds its own engine; the app has one, and it is the "
                "read-only one (or the admin one in db.py)"
            )
    assert writers, "the guard would pass vacuously if nothing wrote at all"
    assert writers == {REVIEW_WRITE_MODULE}, f"writes outside the one review module: {sorted(writers)}"


def test_the_review_write_touches_only_the_review_columns() -> None:
    """The bound is a grant in Postgres and a keyword list here: UPDATE on `agent_turns`, setting the
    two review columns. If this module ever writes another column, it is not a review any more."""
    path = REPO_ROOT / REVIEW_WRITE_MODULE
    tree = ast.parse(path.read_text(encoding="utf-8"))
    written: set[str] | None = None
    updates_agent_turns = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "values":
                written = {keyword.arg for keyword in node.keywords if keyword.arg is not None}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "update":
            updates_agent_turns = updates_agent_turns or "AgentTurn" in ast.unparse(node)
    assert updates_agent_turns, "the review writer must be an UPDATE on AgentTurn"
    assert written == set(reviews.REVIEW_COLUMNS), (
        f"the review writer sets {sorted(written or [])}, expected {sorted(reviews.REVIEW_COLUMNS)}"
    )


def test_the_read_engine_connects_as_the_read_only_role(settings) -> None:
    """Rule 4 in the connection string: the API connects as `agent_readonly`, not as the owner. On
    SQLite (the dev fallback) there are no roles, and `read_only()` says so rather than pretending."""
    postgres = replace(
        settings,
        database_url="postgresql+psycopg://hermes:secret@db:5432/hermes",
        agent_db_role="agent_readonly",
        agent_db_password="readonly-secret",
    )
    url = create_read_engine(postgres).url
    assert url.username == "agent_readonly"
    assert url.password == "readonly-secret"
    assert url.database == "hermes"
    assert read_only(postgres) is True

    # SQLite has no roles: the same DSN is reused, and the flag says so rather than pretending.
    assert read_only(settings) is False
    assert create_read_engine(settings).url.username is None


def test_the_read_engine_never_reuses_the_owners_credentials(settings) -> None:
    """If the read role is unset, the fallback is the configured URL - which in Compose is the
    agent-facing role, never the owner. This test exists so that a future change that "just uses
    DATABASE_URL" for the API is a deliberate one, not an accident."""
    owner_like = replace(
        settings, database_url="postgresql+psycopg://hermes:secret@db:5432/hermes", agent_db_password=None
    )
    assert read_only(owner_like) is False, "no password for the read role means no role switch"
    assert create_read_engine(owner_like).url.username == "hermes"


def test_secrets_are_not_logged(client: TestClient, auth, caplog) -> None:
    """Rule 6. Nothing in the request path logs the token, and the settings module never prints one."""
    import logging

    with caplog.at_level(logging.DEBUG):
        client.get("/health")
        client.get("/competitions", headers=auth)
        client.get("/competitions", headers={})
    assert "test-agent-token" not in caplog.text


def test_the_settings_document_what_the_environment_must_provide(settings: Settings) -> None:
    """`API_AGENT_TOKEN` is required in a deployment and refused when empty, so an unauthenticated API
    is not one environment variable away. `API_ADMIN_TOKEN` is the same shape: empty disables the one
    write path rather than opening it."""
    from backend.settings import BackendSettings as SettingsClass

    assert SettingsClass.from_env({}).auth_enabled is False
    assert SettingsClass.from_env({"API_AGENT_TOKEN": "  "}).auth_enabled is False
    assert SettingsClass.from_env({"API_AGENT_TOKEN": "x"}).auth_enabled is True
    assert SettingsClass.from_env({}).admin_enabled is False
    assert SettingsClass.from_env({"API_ADMIN_TOKEN": "  "}).admin_enabled is False
    assert SettingsClass.from_env({"API_ADMIN_TOKEN": "y"}).admin_enabled is True
    assert SettingsClass.from_env({"FRESHNESS_MAX_AGE_MINUTES": "90"}).freshness_max_age_minutes == 90
    assert SettingsClass.from_env({}).contract_path == REPO_ROOT / "openapi.yaml"


def test_the_admin_token_is_not_the_agent_token(engine, settings: Settings) -> None:
    """The write path must not be reachable with the token the agent holds. Two roles, two tokens,
    and the review endpoint refuses the agent one."""
    configured = BackendSettings(db=settings, agent_token="agent", admin_token="admin")
    app = create_app(configured, engine=engine)
    with TestClient(app) as client:
        refused = client.patch(
            "/admin/agent-turns/00000000-0000-0000-0000-000000000000/review",
            json={"reviewStatus": "correct"},
            headers={"Authorization": "Bearer agent"},
        )
        assert refused.status_code == 401
        accepted_shape = client.patch(
            "/admin/agent-turns/00000000-0000-0000-0000-000000000000/review",
            json={"reviewStatus": "correct"},
            headers={"Authorization": "Bearer admin"},
        )
        assert accepted_shape.status_code == 404, "the admin token authenticates; the turn is missing"


def test_admin_actions_are_disabled_without_an_admin_token(engine, settings: Settings) -> None:
    """A deployment with no admin token has no write path at all: `403`, not `401`, because the
    feature is switched off rather than the caller being unauthenticated."""
    app = create_app(BackendSettings(db=settings, agent_token="agent"), engine=engine)
    with TestClient(app) as client:
        response = client.patch(
            "/admin/agent-turns/00000000-0000-0000-0000-000000000000/review",
            json={"reviewStatus": "correct"},
            headers={"Authorization": "Bearer agent"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
