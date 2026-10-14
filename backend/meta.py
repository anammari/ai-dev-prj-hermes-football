"""The provenance block every factual response carries (`R-F3.3`), and pagination.

Rule 2 is why this module exists: a consumer must be able to print "as of <ts>, source:
football-data.org" without inventing the timestamp. `data_as_of` is the timestamp the data
*describes*, taken from the most recent successful ingestion - never the time of the request, which
is `generated_at`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

SOURCE_UPSTREAM = "football-data.org"
SOURCE_LOCAL = "hermes-football"


def as_utc(value: datetime | None) -> str | None:
    """RFC 3339 with a `Z`, so Postgres (aware) and SQLite (naive) agree on the wire.

    Every timestamp in a response goes through here: the alternative is FastAPI's encoder emitting
    `+00:00` for Postgres rows and a bare naive string for SQLite rows, which is the same API
    answering two different shapes depending on the database.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def aware(value: datetime | None) -> datetime | None:
    """The same timestamps as `datetime`s, for arithmetic on SQLite's naive columns."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def response_meta(
    *,
    request_id: str,
    source: str = SOURCE_UPSTREAM,
    data_as_of: datetime | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "data_as_of": as_utc(data_as_of),
        # The contract documents this as "known delay of the upstream free tier ... when the provider
        # states it". The provider never states it. The measured 1.5-3 minutes live in
        # `_docs/scoping.md` section 3 and in the policy note the agent quotes, and they are a project
        # measurement, not an upstream field - so the API reports null rather than a number the
        # provider did not give us.
        "upstream_delay_minutes": None,
        "generated_at": as_utc(datetime.now(UTC)),
        "request_id": request_id,
    }


def pagination(*, limit: int, offset: int, total: int) -> dict[str, Any]:
    """`total` counts everything that matched, not the page, so `has_more` is meaningful."""
    return {"limit": limit, "offset": offset, "total": total, "has_more": offset + limit < total}
