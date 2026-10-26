"""Compose is policy: no socket, no owner secret in the wrong container, limits and probes present.

These rules are written in `_docs/product-spec.md` §4 and `AGENTS.md` rule 5, and every one of them is
a property of the Compose file rather than of a handler. A reviewer should not have to re-read 400
lines of YAML after a service is added, so the invariants are asserted here.

The test parses `docker-compose.yml` directly with PyYAML (merge keys resolved) and the observability
file when it exists. It is a unit test: no Docker daemon is needed.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from db.settings import REPO_ROOT

MAIN = REPO_ROOT / "docker-compose.yml"
OBS = REPO_ROOT / "docker-compose.observability.yml"

#: One-shot or test targets: they are expected to exit, so a healthcheck would be meaningless.
ONE_SHOT = {"migrate", "models", "tests", "frontend-e2e"}

#: `ingest` is a long-running scheduler with no HTTP surface; its heartbeat is the run ledger. It is
#: the one documented exception, and it still carries a resource limit.
NO_HEALTHCHECK = {"ingest"}


def _document(path: Path = MAIN) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _services(path: Path = MAIN) -> dict:
    return (_document(path).get("services") or {})


def test_no_service_mounts_the_docker_socket() -> None:
    for path in (MAIN, OBS):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert "/var/run/docker.sock" not in text, f"{path.name} mounts the Docker socket"


def test_no_service_runs_privileged_or_on_the_host_network() -> None:
    for path in (MAIN, OBS):
        if not path.exists():
            continue
        for name, service in _services(path).items():
            assert not service.get("privileged"), f"{name} is privileged"
            assert service.get("network_mode") != "host", f"{name} uses host networking"
            assert not service.get("pid"), f"{name} shares the host PID namespace"


def test_every_long_running_service_has_limits_and_a_healthcheck() -> None:
    missing_limits: list[str] = []
    missing_health: list[str] = []
    for path in (MAIN, OBS):
        if not path.exists():
            continue
        for name, service in _services(path).items():
            if name in ONE_SHOT:
                continue
            if not service.get("mem_limit") or not service.get("cpus"):
                missing_limits.append(name)
            if name not in NO_HEALTHCHECK and not service.get("healthcheck"):
                missing_health.append(name)
    assert not missing_limits, f"services without mem_limit/cpus: {missing_limits}"
    assert not missing_health, f"services without a healthcheck: {missing_health}"


def test_only_the_two_expected_ports_are_published_by_the_default_stack() -> None:
    published = {name for name, service in _services().items() if service.get("ports")}
    assert published == {"backend", "frontend"}, f"published ports moved: {sorted(published)}"
    backend_port = _services()["backend"]["ports"][0]
    frontend_port = _services()["frontend"]["ports"][0]
    assert "BACKEND_PORT" in str(backend_port)
    assert "FRONTEND_PORT" in str(frontend_port)


def test_grafana_is_bound_to_loopback_only() -> None:
    if not OBS.exists():
        return
    grafana = _services(OBS)["grafana"]
    ports = [str(item) for item in grafana.get("ports") or []]
    assert ports, "grafana publishes no port"
    assert all(port.startswith("127.0.0.1:") for port in ports), f"grafana is not loopback-bound: {ports}"


def test_the_api_never_receives_the_owner_password() -> None:
    """Rule 4 as an environment fact: the read engine uses `agent_readonly`, so the API is handed that
    DSN. The owner password belongs to `db`, `ingest`, `migrate` and the test fixtures only."""
    backend_env = _services()["backend"].get("environment") or {}
    assert "POSTGRES_PASSWORD" not in backend_env, "backend receives the owner password"
    assert "POSTGRES_USER" not in backend_env
    database_url = str(backend_env.get("DATABASE_URL", ""))
    assert "AGENT_DB_ROLE" in database_url, database_url
    assert "POSTGRES_USER" not in database_url
    assert "AGENT_ADMIN_DB_PASSWORD" in backend_env, "the review write needs its narrow role"


def test_the_gateway_reviewer_and_oncall_hold_no_owner_credentials() -> None:
    for name in ("hermes", "hermes-review", "oncall", "mcp-server", "frontend"):
        service = _services().get(name)
        if service is None:
            continue
        env = service.get("environment") or {}
        assert "POSTGRES_PASSWORD" not in env, f"{name} receives the owner password"
        assert "DATABASE_URL" not in env or "AGENT" in str(env["DATABASE_URL"]), name


def test_the_state_volumes_are_named() -> None:
    volumes = set((_document().get("volumes") or {}).keys())
    assert {"pgdata", "ollama-data"} <= volumes
