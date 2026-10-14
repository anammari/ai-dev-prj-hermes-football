"""The query layer: DB rows in, contract-shaped objects out.

Routers validate and attach provenance; services answer questions. Everything a service does is
read-only, and everything it does is portable between Postgres and the SQLite dev fallback - no
dialect-specific SQL, no JSON operators (`R-F2.3`). Where that costs a query or two - the freshness
report counts rows per competition - the clarity is worth more than the milliseconds on a
13-competition database.

A service returns the *body* of a contract response and, separately, the timestamp that body
describes. The `meta` block itself is an HTTP concern the router assembles, because it carries the
request id and the generation time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Answer:
    """A single contract object, plus the upstream timestamp it describes (`R-F3.3`)."""

    data: dict[str, Any]
    data_as_of: datetime | None = None


@dataclass(slots=True)
class Page:
    """One page of a list endpoint, before the envelope is wrapped around it."""

    data: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    data_as_of: datetime | None = None
