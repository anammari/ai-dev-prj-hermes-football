"""The drift tests: the implementation against `openapi.yaml`, in both directions.

`README.md` criterion 5 asks for a test that fails when the backend drifts from the contract. The
tests here do not assert that `/competitions` returns a `code` and a `name`; they read the contract and
assert that what the API sends is what the contract says. Three consequences are worth naming:

* A response field renamed, removed, or made non-nullable fails the sweep below, because the sweep
  validates every implemented response body against the schema in the file.
* A route that exists in the code but not in the contract fails, and so does a documented operation
  with no route - except the two `/admin` operations M3 deliberately stubs, which are listed by name
  in `backend/routers/admin.py` and are checked to refuse rather than to be forgotten.
* The validator itself is tested. `test_the_validator_fails_on_a_drifted_response` proves the check
  can go red, because a schema check that accepts everything is decoration.

The app's *own* generated OpenAPI document is what the route and parameter tests compare against. It
is never served (`/openapi.json` is a 404, checked below); it is the app's honest statement of what it
registers, which is exactly the thing that must not drift from the file.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import backend
from backend.routers import admin
from tests import api_helpers
from tests.api_helpers import (
    CONTRACT,
    SCHEMAS,
    operations,
    request_for_with,
    response_schema,
    validate,
)

#: The parameters this sweep must not take from the contract as-is (`tests/api_helpers.py` explains
#: each one). The stack sweep uses the same table, minus the fake-embedder-only entry.
SWEEP_OVERRIDES: dict[str, dict[str, Any]] = api_helpers.SWEEP_OVERRIDES_UNIT

IMPLEMENTED = [
    operation_id
    for operation_id, (method, _path, _node) in operations().items()
    if method == "GET" and operation_id not in admin.UNIMPLEMENTED
]


def call(client: TestClient, operation_id: str, **kwargs: Any):
    method, path, params = request_for_with(operation_id, overrides=SWEEP_OVERRIDES.get(operation_id, {}))
    return client.request(method, path, params=params, **kwargs)


def generated(app: FastAPI) -> dict[str, Any]:
    """The document FastAPI would publish for this app, which is what must agree with the file."""
    return app.openapi()


def generated_operations(spec: dict[str, Any]) -> dict[str, tuple[str, str, dict[str, Any]]]:
    found: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method in api_helpers.HTTP_METHODS:
                found[operation["operationId"]] = (method.upper(), path, operation)
    return found


def generated_parameters(spec: dict[str, Any], path: str, method: str) -> dict[tuple[str, str], bool]:
    entries = spec["paths"][path][method.lower()].get("parameters", [])
    return {(entry["in"], entry["name"]): bool(entry.get("required")) for entry in entries}


def generated_parameter_schema(spec: dict[str, Any], path: str, method: str, name: str) -> dict[str, Any]:
    entries = spec["paths"][path][method.lower()].get("parameters", [])
    for entry in entries:
        if entry["name"] == name:
            return api_helpers.collapsed(entry.get("schema") or {})
    raise KeyError(f"{method} {path} has no parameter {name}")


def app_routes(app: FastAPI) -> list[Any]:
    """Every route the app actually serves, walked out of the router tree.

    Deliberately *not* `app.openapi()`: FastAPI leaves a route registered with `include_in_schema=
    False` out of the generated document, and a route that is served but invisible to this suite is
    exactly the drift it exists to catch. A review probe added such a route to the unauthenticated
    router and the whole suite passed; this walker is the fix.
    """
    found: list[Any] = []
    seen: set[int] = set()

    def walk(router: Any) -> None:
        for route in getattr(router, "routes", []):
            if isinstance(route, APIRoute):
                found.append(route)
                continue
            nested = getattr(route, "original_router", None)
            if nested is not None and id(nested) not in seen:
                seen.add(id(nested))
                walk(nested)

    walk(app.router)
    return found


def served_operations(app: FastAPI) -> dict[str, list[tuple[str, str]]]:
    """operationId -> [(METHOD, path)], from the router tree rather than from a mapping that a
    duplicate id would silently overwrite."""
    served: dict[str, list[tuple[str, str]]] = {}
    for route in app_routes(app):
        methods = sorted(method for method in route.methods if method != "HEAD")
        for method in methods:
            served.setdefault(route.operation_id, []).append((method, route.path))
    return served


# ------------------------------------------------------------------------------------------------
# Coverage, both ways
# ------------------------------------------------------------------------------------------------


def test_the_contract_and_the_app_serve_the_same_operations(api_app: FastAPI) -> None:
    """Every documented operation is routed, and every route is documented. No subsets.

    Read from the router tree, so a route registered with `include_in_schema=False` - served but
    absent from the generated document - is still a route this test can see.
    """
    served = served_operations(api_app)
    documented = {operation_id: [(method, path)] for operation_id, (method, path, _n) in operations().items()}
    assert set(served) == set(documented), (
        f"routed but undocumented: {sorted(set(served) - set(documented))}; "
        f"documented but unrouted: {sorted(set(documented) - set(served))}"
    )
    for operation_id, routes in documented.items():
        assert served[operation_id] == routes, (
            f"{operation_id} is {served[operation_id]} in the app, {routes} in the contract"
        )


def test_operation_ids_are_unique() -> None:
    """`operation_id` is the identity every tool, test and client uses; two operations sharing one
    would collapse silently in every mapping built from this file."""
    seen: dict[str, str] = {}
    for path, item in CONTRACT["paths"].items():
        for method, node in item.items():
            if method not in api_helpers.HTTP_METHODS:
                continue
            key = node["operationId"]
            assert key not in seen, f"{key} is used by both {seen[key]} and {method.upper()} {path}"
            seen[key] = f"{method.upper()} {path}"


def test_the_app_does_not_reuse_an_operation_id_either(api_app: FastAPI) -> None:
    """The same rule on the app's side. A second route reusing a documented id would shadow the real
    one in every mapping keyed by `operationId` - including this suite's - while both answered."""
    served = served_operations(api_app)
    duplicated = {operation_id: routes for operation_id, routes in served.items() if len(routes) > 1}
    assert not duplicated, f"one operationId, several routes: {duplicated}"
    assert len(served) == len(app_routes(api_app)), "every route is reachable through its operationId"


def test_every_parameter_is_declared_with_the_same_name_and_requiredness(api_app: FastAPI) -> None:
    """`teamId` is not `team_id`, and a required parameter is not optional."""
    spec = generated(api_app)
    for operation_id, (method, path, _node) in operations().items():
        documented = {
            (entry["in"], entry["name"]): bool(entry.get("required"))
            for entry in api_helpers.parameters(operation_id)
        }
        declared = generated_parameters(spec, path, method)
        assert declared == documented, f"{operation_id}: app declares {declared}, contract says {documented}"


#: What a parameter's schema has to agree on: the type a client sends, and the bounds that decide
#: whether the server accepts it. A wrong `le=` is not cosmetic - the contract-legal request is then
#: rejected with a 400 and every client that reads the file is wrong.
#:
#: `enum` is absent on purpose. The app does not restate the contract's enums in Python; it validates
#: the value against the contract's own list at request time (`backend/contract.py`), so the
#: guarantee is behavioural and is tested as behaviour below. Restating them here would be the second
#: copy of the same list that this whole file exists to avoid.
COMPARED_PARAMETER_KEYS = (
    "type",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "format",
    "pattern",
    "default",
)


#: `format: int64` is a real constraint - the id columns and the driver binds are 64-bit - but it is
#: spelled as a format, so the app states it as a bound. The values are the range that format means.
INTEGER_RANGES = {"int64": (-(2**63), 2**63 - 1), "int32": (-(2**31), 2**31 - 1)}


def bound_implied_by_format(key: str, documented: dict[str, Any], declared: dict[str, Any]) -> bool:
    """True when the app's `minimum`/`maximum` is just the contract's `format` written out."""
    limits = INTEGER_RANGES.get(documented.get("format", ""))
    if limits is None or key not in ("minimum", "maximum"):
        return False
    return declared.get(key) == (limits[0] if key == "minimum" else limits[1])


def test_every_parameter_schema_matches_the_contract(api_app: FastAPI) -> None:
    """The bounds the contract publishes are the bounds the app enforces.

    Two deliberate exemptions, both narrow: the app may spell a declared `format: int64` as its range
    (never anything else, and never in the other direction), and `format` on a *number* is skipped
    because OpenAPI's `float`/`double` say nothing a validator enforces - the Python type is the
    constraint. Everything else must agree exactly, because a stricter `le=` rejects a request the
    published contract allows.
    """
    spec = generated(api_app)
    for operation_id, (method, path, _node) in operations().items():
        for entry in api_helpers.parameters(operation_id):
            name = entry["name"]
            documented = api_helpers.parameter_schema(operation_id, name)
            declared = generated_parameter_schema(spec, path, method, name)
            for key in COMPARED_PARAMETER_KEYS:
                if key not in documented and key not in declared:
                    continue
                if key == "format" and documented.get("type") != "string":
                    continue
                if key not in documented and bound_implied_by_format(key, documented, declared):
                    continue
                assert declared.get(key) == documented.get(key), (
                    f"{operation_id}.{name}: app declares {key}={declared.get(key)!r}, "
                    f"contract says {documented.get(key)!r}"
                )


ENUM_PARAMETERS = [
    (operation_id, entry["name"], entry["in"], api_helpers.parameter_schema(operation_id, entry["name"])["enum"])
    for operation_id, (_method, _path, _node) in operations().items()
    for entry in api_helpers.parameters(operation_id)
    if "enum" in api_helpers.parameter_schema(operation_id, entry["name"])
]


def test_the_contract_does_document_some_enums() -> None:
    """Guards the test below from passing because it found nothing to check."""
    assert len(ENUM_PARAMETERS) >= 4, ENUM_PARAMETERS


@pytest.mark.parametrize(("operation_id", "name", "location", "allowed"), ENUM_PARAMETERS)
def test_an_enum_parameter_rejects_a_value_outside_the_contract(
    client: TestClient, auth: dict[str, str], operation_id: str, name: str, location: str, allowed: list
) -> None:
    """The enums are enforced by reading the contract at request time, so this is where that promise
    is checked: a value the file does not list is a 400 that names the parameter, whether it sits in
    the path or the query string. `allowed[0]` and `'x'` cannot both be legal unless the enum is
    permissive, which the guard above rules out."""
    method, path, params = request_for_with(operation_id, overrides={name: "not-in-the-enum"})
    if location == "path":
        path = path.replace("{" + name + "}", "not-in-the-enum")
    response = client.request(method, path, params=params, headers=auth)
    assert response.status_code == 400, f"{operation_id} accepted an unlisted {name}: {response.text}"
    body = response.json()
    assert body["error"]["code"] == "invalid_parameter"
    assert name in body["error"]["message"], body["error"]


def test_every_documented_path_parameter_is_in_the_path() -> None:
    for operation_id, (_method, path, _node) in operations().items():
        for entry in api_helpers.parameters(operation_id):
            if entry["in"] == "path":
                assert "{" + entry["name"] + "}" in path, f"{operation_id}: {entry['name']} is not a template"


def test_the_competition_enum_is_a_reviewed_list_of_what_ingestion_verified() -> None:
    """`CompetitionCode` is the one hardcoded list in the contract, and it is deliberate: a code the
    plan cannot serve is rejected with a 400 instead of being answered with silence (`AGENTS.md` rule
    3 says never to hardcode the list *upstream*; here it is the reviewed set this deployment can
    ingest). This test keeps the list and its per-code documentation from drifting apart, and the
    integration suite checks it against the competitions the live database actually holds.
    """
    schema = api_helpers.resolve(SCHEMAS["CompetitionCode"])
    codes = schema["enum"]
    assert len(codes) == len(set(codes)) == 13, sorted(codes)
    described = schema["x-enum-descriptions"]
    assert set(described) == set(codes), "every accepted code explains itself, and nothing else does"
    assert all(described[code].strip() for code in codes)


# ------------------------------------------------------------------------------------------------
# Every implemented response, against its schema
# ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("operation_id", IMPLEMENTED)
def test_the_response_matches_the_contract(client: TestClient, auth: dict[str, str], seeded, operation_id: str) -> None:
    """One test per operation, so a failure names the operation and the field."""
    node = operations()[operation_id][2]
    statuses = [status for status in node["responses"] if status.startswith("2")]
    assert statuses, f"{operation_id} has no success response"
    response = call(client, operation_id, headers=auth)
    assert response.status_code == int(statuses[0]), response.text

    media = node["responses"][statuses[0]].get("content") or {}
    if "application/json" not in media:
        # `/openapi.yaml` and `/docs` answer with a document, and the contract describes the media
        # type rather than a payload. Check that, and check there is a body.
        assert response.content
        for declared in media:
            assert response.headers["content-type"].startswith(declared.split(";")[0]), (
                f"{operation_id}: served {response.headers['content-type']}, contract says {declared}"
            )
        return

    schema = response_schema(operation_id, statuses[0])
    assert schema is not None, f"{operation_id}: no JSON schema for {statuses[0]}"
    body = response.json()
    validate(body, schema, where=operation_id)
    # A validator run over an empty list checks nothing: if the contract says `data`, the sweep must
    # have produced some, or the item schema is untested and this test is quietly weaker.
    if isinstance(schema, dict) and "data" in (schema.get("properties") or {}):
        assert body["data"], f"{operation_id}: the sweep produced no data to validate"


def test_every_documented_error_response_is_the_contract_error_shape(
    client: TestClient, auth: dict[str, str], seeded
) -> None:
    """The 400/401/404/503 bodies are the documented `ErrorResponse`, on every path that can produce
    one - the errors a client actually has to parse."""
    cases = [
        ("getStandings", {"code": "XX"}, auth, 400, "invalid_parameter"),
        ("getMatch", {"matchId": 999999}, auth, 404, "not_found"),
        ("getTeam", {"teamId": 999999}, auth, 404, "not_found"),
        ("listCompetitions", {}, {}, 401, "unauthorized"),
        ("listCompetitions", {}, {"Authorization": "Bearer wrong"}, 401, "unauthorized"),
        ("getStandings", {"code": "WC"}, auth, 503, "data_not_available"),
        ("getHeadToHead", {"teamA": 57, "teamB": 57}, auth, 400, "invalid_parameter"),
        ("searchKnowledge", {"q": "a"}, auth, 400, "invalid_parameter"),
    ]
    for operation_id, overrides, headers, expected_status, expected_code in cases:
        method, path, params = request_for_with(
            operation_id, overrides={**SWEEP_OVERRIDES.get(operation_id, {}), **overrides}
        )
        response = client.request(method, path, params=params, headers=headers)
        assert response.status_code == expected_status, f"{operation_id}: {response.status_code} {response.text}"
        body = response.json()
        validate(body, SCHEMAS["ErrorResponse"], where=f"{operation_id} {expected_status}")
        assert body["error"]["code"] == expected_code
        assert body["error"]["request_id"]

    # An unrouted path is an ErrorResponse too, not Starlette's `{"detail": "Not Found"}`.
    missing = client.get("/not-a-route", headers=auth)
    assert missing.status_code == 404
    validate(missing.json(), SCHEMAS["ErrorResponse"], where="unrouted path")


# ------------------------------------------------------------------------------------------------
# The declared stubs, and the promise that nothing is silently missing
# ------------------------------------------------------------------------------------------------


def test_unimplemented_operations_are_declared_and_explain_themselves(client: TestClient, auth: dict[str, str]) -> None:
    """The two `/admin` operations answer 404 with the milestone that owns them, rather than a bare
    `Not Found` that would read like a bug."""
    for operation_id, (milestone, _why) in admin.UNIMPLEMENTED.items():
        method, path, node = operations()[operation_id]
        assert node["operationId"] == operation_id
        url = path
        for spec in node.get("parameters", []):
            if spec["in"] == "path":
                url = url.replace("{" + spec["name"] + "}", str(uuid.uuid4()))
        response = client.request(method, url, json={}, headers=auth)
        assert response.status_code == 404, response.text
        body = response.json()
        validate(body, SCHEMAS["ErrorResponse"], where=operation_id)
        assert body["error"]["code"] == "not_found"
        assert body["error"]["details"] == {"operation": operation_id, "owner": milestone}
        assert operation_id in body["error"]["message"]


def test_no_unimplemented_operation_is_an_agent_tool() -> None:
    """Rule 3/8: the gap must never be something the agent depends on. A declared MCP tool that the
    backend does not implement would be a broken tool in the agent's schema."""
    for operation_id in admin.UNIMPLEMENTED:
        assert "x-mcp-tool" not in operations()[operation_id][2], (
            f"{operation_id} is both unimplemented and exposed as an MCP tool"
        )
    exposed = {operation_id for operation_id, (_m, _p, node) in operations().items() if "x-mcp-tool" in node}
    assert exposed <= set(IMPLEMENTED) | set(admin.UNIMPLEMENTED)


def test_admin_operations_are_the_only_writes_in_the_contract() -> None:
    """The agent's data path is read-only (`AGENTS.md` rule 4): the only writes are the two `/admin`
    operations, one of which (the review decision) M5 implements and the other (the ingest trigger)
    M6 still owns. A write appearing anywhere else is a finding, not a design choice."""
    writes = {
        operation_id
        for operation_id, (method, _path, _node) in operations().items()
        if method in {"POST", "PUT", "PATCH", "DELETE"}
    }
    assert writes == set(admin.UNIMPLEMENTED) | {"reviewAgentTurn"}, writes


def test_the_implemented_write_is_the_documented_review(client: TestClient, admin_auth: dict[str, str], seeded) -> None:
    """The review operation is declared with a `200`, a `400`, a `403` and a `404`; this checks the
    first, the second and the contract shape of the body it returns."""
    turn_id = seeded.turns["tool"]
    response = client.patch(
        f"/admin/agent-turns/{turn_id}/review",
        json={"reviewStatus": "wrong", "note": "Said the match was live; the free tier is delayed by design."},
        headers=admin_auth,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    schema = response_schema("reviewAgentTurn", "200")
    assert schema is not None
    validate(body, schema, where="reviewAgentTurn")
    data = body["data"]
    assert data["id"] == turn_id
    assert data["review_status"] == "wrong"
    assert data["review_note"].startswith("Said the match was live")
    assert body["meta"]["source"] == "hermes-football"

    missing = client.patch(
        f"/admin/agent-turns/{uuid.uuid4()}/review", json={"reviewStatus": "correct"}, headers=admin_auth
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    bad_enum = client.patch(
        f"/admin/agent-turns/{turn_id}/review", json={"reviewStatus": "brilliant"}, headers=admin_auth
    )
    assert bad_enum.status_code == 400
    assert bad_enum.json()["error"]["code"] == "invalid_parameter"


# ------------------------------------------------------------------------------------------------
# The contract is the only specification, and it is served as written
# ------------------------------------------------------------------------------------------------


def test_the_version_matches_the_contract(api_app: FastAPI) -> None:
    assert backend.__version__ == CONTRACT["info"]["version"], (
        "backend/__init__.py and openapi.yaml disagree about the version; /health would report one "
        "and the contract the other"
    )
    assert generated(api_app)["info"]["version"] == CONTRACT["info"]["version"]


def test_the_contract_file_is_served_verbatim(client: TestClient) -> None:
    response = client.get("/openapi.yaml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/yaml")
    assert response.text == api_helpers.CONTRACT_PATH.read_text(encoding="utf-8")


def test_the_generated_document_is_not_served(client: TestClient) -> None:
    """A second, generated specification is exactly the drift this suite exists to prevent."""
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_swagger_ui_points_at_the_file(client: TestClient) -> None:
    body = client.get("/docs").text
    assert "/openapi.yaml" in body


# ------------------------------------------------------------------------------------------------
# The validator itself
# ------------------------------------------------------------------------------------------------


def test_the_validator_fails_on_a_drifted_response(client: TestClient, auth: dict[str, str], seeded) -> None:
    """Criterion 5: prove the check above can fail. A renamed field, a dropped required field and a
    null where the contract promises a value must each be rejected."""
    body = client.get(f"/matches/{api_helpers.MATCH_ID}", headers=auth).json()
    schema = response_schema("getMatch")
    validate(body, schema, where="baseline")  # the clean body passes, so the failures below are real

    renamed = copy.deepcopy(body)
    renamed["data"]["matchId"] = renamed["data"].pop("id")
    with pytest.raises(AssertionError):
        validate(renamed, schema, where="renamed field")

    dropped = copy.deepcopy(body)
    dropped["data"].pop("utc_date")
    with pytest.raises(AssertionError):
        validate(dropped, schema, where="dropped required field")

    nulled = copy.deepcopy(body)
    nulled["data"]["competition"] = None
    with pytest.raises(AssertionError):
        validate(nulled, schema, where="null for a non-nullable field")

    extra = copy.deepcopy(body)
    extra["data"]["extra_field"] = "surprise"
    assert json.loads(json.dumps(extra)) == extra  # still JSON, and still accepted: the contract does
    # not close its objects, so an added field is not a drift the contract forbids.


def test_every_schema_in_the_contract_is_translatable() -> None:
    """The validator is only as good as the translation: if a schema used a keyword it did not
    understand, the sweep would silently stop checking that part of it."""
    for name, node in SCHEMAS.items():
        translated = api_helpers.json_schema(node)
        assert isinstance(translated, dict), name
        if node.get("type") == "object" or "properties" in node:
            assert translated, f"{name} translated to an empty schema, which accepts anything"
