"""The schema and the contract, checked against each other in both directions.

The contract is the source of truth for what the API serves; `db/models.py` is what the database
stores. This test walks the contract schema by schema and fails on either kind of surprise: a contract
property with nowhere to live, or a column no contract property asks for. Everything that legitimately
has no counterpart is written down in `tests/contract_map.py` with a reason, so a new contract field
cannot be waved through by quietly adding it to an allowlist.
"""

from __future__ import annotations

import yaml
from sqlalchemy import Table

from db.models import Base
from db.settings import REPO_ROOT
from tests.contract_map import LOCAL_ONLY, LOCAL_TABLES, SCHEMAS, UNMAPPED_SCHEMAS


def _contract() -> dict:
    spec = yaml.safe_load((REPO_ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    return spec["components"]["schemas"]


class Check:
    """Collects every disagreement before failing, so one run reports all of them."""

    def __init__(self) -> None:
        self.problems: list[str] = []

    def say(self, message: str) -> None:
        self.problems.append(message)


def _resolve(schema: dict, contract: dict) -> dict:
    """Follow a single `$ref`, which is all this contract uses."""
    if "$ref" in schema:
        return contract[schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def _inline(name: str) -> bool:
    return bool(SCHEMAS.get(name, {}).get("inline"))


def _properties(name: str, contract: dict, check: Check) -> dict[str, dict]:
    """A schema's properties: from the contract, or from the map for an inlined object."""
    if _inline(name):
        declared = SCHEMAS[name]["properties"]
        if not declared:
            check.say(f"{name}: inlined objects still need their properties written down")
        return {prop: {} for prop in declared}
    schema = contract[name]
    props: dict[str, dict] = {}
    for part in schema.get("allOf", []):
        props.update(_resolve(part, contract).get("properties", {}))
    props.update(schema.get("properties", {}))
    if not props:
        check.say(f"{name}: no properties found in the contract (the test would check nothing)")
    return props


def _chain(schema_name: str) -> list[str]:
    """A schema plus the schemas it extends, parent last."""
    names = [schema_name]
    entry = SCHEMAS[schema_name]
    while entry.get("extends"):
        names.append(entry["extends"])
        entry = SCHEMAS[entry["extends"]]
    return names


def _expectation(schema_name: str, prop: str) -> str | None:
    """An expectation for a property, inherited from the schema it extends when it has none."""
    entry = SCHEMAS[schema_name]
    while True:
        if prop in entry["properties"]:
            return entry["properties"][prop]
        if entry.get("extends"):
            entry = SCHEMAS[entry["extends"]]
        else:
            return None


def _columns_used_by(schema_name: str, contract: dict, check: Check, prefix: str = "") -> set[str]:
    """Every column this schema occupies, following nested objects.

    `prefix` is what the parents already contributed: `Match.score.full_time.home` arrives here as
    `score_full_time_`, so the last segment is the property name plus an underscore.
    """
    columns: set[str] = set()
    # The contract flattens `allOf`, so `_properties` already carries the inherited properties; the
    # expectations for those come from the parent through `_expectation`.
    for prop, schema in _properties(schema_name, contract, check).items():
        expectation = _expectation(schema_name, prop)
        if expectation is None:
            check.say(f"{schema_name}.{prop}: no expectation in tests/contract_map.py")
            continue
        kind, _, argument = expectation.partition(":")
        if kind in {"column", "alias"}:
            columns.add(prefix + argument)
        elif kind == "nested":
            columns |= _columns_used_by(argument, contract, check, f"{prefix}{prop}_")
        elif kind == "json":
            columns.add(prefix + prop)
        elif kind == "derived" and not argument:
            check.say(f"{schema_name}.{prop}: a derived field needs its reason")
        elif _resolve(schema, contract).get("properties") and kind == "derived":
            check.say(f"{schema_name}.{prop}: nested objects are flattened, not derived")
    return columns


def test_every_contract_schema_is_accounted_for() -> None:
    contract = _contract()
    declared = {name for name in SCHEMAS if not _inline(name)}
    unaccounted = set(contract) - declared - set(UNMAPPED_SCHEMAS)
    assert not unaccounted, f"new contract schemas need a home or a reason: {sorted(unaccounted)}"
    stale = (declared | set(UNMAPPED_SCHEMAS)) - set(contract)
    assert not stale, f"tests/contract_map.py mentions schemas the contract no longer has: {sorted(stale)}"
    for reason in UNMAPPED_SCHEMAS.values():
        assert reason.strip(), "an unmapped schema needs a reason"


def test_every_contract_property_has_an_expectation() -> None:
    contract = _contract()
    check = Check()
    for schema_name in SCHEMAS:
        if SCHEMAS[schema_name].get("nested_only"):
            continue
        _columns_used_by(schema_name, contract, check)
    assert not check.problems, "\n".join(check.problems)


def test_every_top_level_expectation_names_a_real_column() -> None:
    """A typo in an alias or a column name must fail here, not at query time."""
    check = Check()
    for schema_name, entry in SCHEMAS.items():
        table: Table = Base.metadata.tables[entry["table"]]
        # A schema reached through a parent property carries that property's prefix; they are
        # declared in the map so the columns can still be checked by name here.
        prefixes = entry.get("prefixes") or [""]
        for prop, expectation in entry["properties"].items():
            kind, _, argument = expectation.partition(":")
            if kind == "column":
                for prefix in prefixes:
                    if prefix + argument not in table.columns:
                        check.say(f"{schema_name}.{prop}: {table.name} has no column {prefix + argument!r}")
            elif kind == "alias" and argument not in table.columns:
                check.say(f"{schema_name}.{prop}: {table.name} has no column {argument!r}")
            elif kind == "relation" and argument not in Base.metadata.tables:
                check.say(f"{schema_name}.{prop}: no table {argument!r}")
        # Inherited properties are declared on the parent; make sure every one of them resolves.
        if _inline(schema_name):
            continue
        for prop in _properties(schema_name, contract=_contract(), check=check):
            if _expectation(schema_name, prop) is None:
                check.say(f"{schema_name}.{prop}: no expectation, here or on a schema it extends")
    assert not check.problems, "\n".join(check.problems)


def test_every_column_is_asked_for_by_the_contract_or_explained() -> None:
    """The other direction: nothing in the schema exists by accident."""
    contract = _contract()
    check = Check()
    for table_name, table in Base.metadata.tables.items():
        if table_name in LOCAL_TABLES:
            continue
        wanted = {
            column
            for schema_name, entry in SCHEMAS.items()
            if entry["table"] == table_name
            for column in _columns_used_by(schema_name, contract, check)
        }
        allowed = LOCAL_ONLY.get(table_name, {})
        for column in table.columns:
            if column.name in wanted or column.name in allowed or "*" in allowed:
                continue
            check.say(
                f"{table_name}.{column.name}: no contract property asks for it, and LOCAL_ONLY does not explain it"
            )
    assert not check.problems, "\n".join(check.problems)
