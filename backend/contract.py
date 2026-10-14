"""The contract, loaded at startup and used as the source of truth at runtime.

Three things come out of `openapi.yaml` here rather than being retyped in Python:

* the **enums** (`CompetitionCode`, `MatchStatus`, `ReviewStatus`), so a query parameter is validated
  against the same list a reader of the contract sees. `CompetitionCode` in particular is
  deliberately not hardcoded anywhere in the codebase (`AGENTS.md` rule 3: the upstream competition
  list is plan-filtered, so the contract's reviewed enum is the only copy);
* the **document version**, so `/health` and `info.version` cannot disagree;
* the **operation list**, which is what `tests/test_api_contract.py` holds the route table to.

Reading a 60-page YAML once at startup costs nothing and removes a whole class of drift.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.errors import InvalidParameter


class Contract:
    """A read-only view of the reviewed contract file."""

    def __init__(self, spec: dict[str, Any], *, source: Path) -> None:
        self.spec = spec
        self.source = source

    @property
    def version(self) -> str:
        return str(self.spec["info"]["version"])

    @property
    def paths(self) -> dict[str, Any]:
        return self.spec["paths"]

    @property
    def schemas(self) -> dict[str, Any]:
        return self.spec["components"]["schemas"]

    def enum(self, schema_name: str) -> tuple[str, ...]:
        """The members of a contract enum schema, in the order the contract lists them."""
        values = self.schemas[schema_name].get("enum")
        if not values:
            raise KeyError(f"{schema_name} is not an enum in {self.source.name}")
        return tuple(str(value) for value in values if value is not None)

    def property_enum(self, schema_name: str, property_name: str) -> tuple[str, ...]:
        """The members of an enum declared inline on a property (`IngestRun.status`), as opposed to a
        schema that is an enum in its own right (`MatchStatus`). Query filters are validated against
        the same list a reader of the contract sees."""
        values = self.schemas[schema_name]["properties"][property_name].get("enum")
        if not values:
            raise KeyError(f"{schema_name}.{property_name} is not an enum in {self.source.name}")
        return tuple(str(value) for value in values if value is not None)

    def _check(self, allowed: tuple[str, ...], value: str | None, *, field: str) -> str | None:
        if value is None:
            return None
        if value not in allowed:
            raise InvalidParameter(
                f"{field} must be one of: {', '.join(allowed)}",
                details={"parameter": field, "value": value, "allowed": list(allowed)},
            )
        return value

    def checked_enum(self, schema_name: str, value: str | None, *, field: str) -> str | None:
        """`value` when the contract allows it, `None` when it was not given, else 400.

        An out-of-vocabulary value is a *client* error, not a server one: the contract says so in
        `CompetitionCode`'s own description ("a code outside it is rejected rather than served
        empty"), and `ErrorResponse` has the code for it - `invalid_parameter`.
        """
        return self._check(self.enum(schema_name), value, field=field)

    def checked_property_enum(
        self, schema_name: str, property_name: str, value: str | None, *, field: str
    ) -> str | None:
        return self._check(self.property_enum(schema_name, property_name), value, field=field)


#: The signed 64-bit range, which is what the contract's `format: int64` means and all the database can
#: bind: the id columns are `bigint`, and so are the driver's LIMIT/OFFSET parameters. A parameter
#: declared with those bounds turns `10**30` into the 400 the contract documents instead of the
#: `OverflowError` that used to surface as a 500.
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


def load_contract(path: Path) -> Contract:
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or "paths" not in spec or "components" not in spec:
        raise ValueError(f"{path} is not an OpenAPI document")
    return Contract(spec, source=path)
