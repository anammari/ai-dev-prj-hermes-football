"""League tables, including the point-in-time question.

`snapshot` is what makes "where were they in November?" answerable: the table is stored one row per
team per daily snapshot rather than overwritten, so the API picks the newest snapshot on or before the
date asked for (`R-F2.1`, `_docs/data-model.md`).

Only the **total** table is served. The provider also publishes `HOME` and `AWAY` splits, which no
contract field asks for, so they stay in the database (`StandingsTable.type` reports `TOTAL` so a
client is never in doubt about which one it got). No stored table carries a group label today - the
retained volume has zero such rows - so `group` is echoed when every row agrees on one and omitted
otherwise. Serving a grouped competition one table at a time would need the contract to gain a way to
ask for one, and that is a change to make in the pull request that has the data for it.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.errors import DataNotAvailable, NotFound
from backend.schemas import standing_row, standings_table
from backend.services import Answer
from backend.services.catalog import has_standings, require_competition, team_index
from db.models import Standing

#: The table a league position comes from. `NULL` is included because the column is optional in the
#: schema, and a provider that publishes one untyped table should not vanish from the API.
_TOTAL = or_(Standing.table_type == "TOTAL", Standing.table_type.is_(None))


def get_standings(
    session: Session,
    code: str,
    *,
    season: int | None = None,
    snapshot: date | None = None,
    matchday: int | None = None,
) -> Answer:
    """The stored table, and when it was written.

    `data_as_of` is `standings.updated_at` - the moment ingestion wrote the snapshot - because a
    standings row carries no provider timestamp of its own. That is a different question from the
    provider's `lastUpdated` stamp, and `/meta/freshness` is where the age of the last successful run
    is reported.
    """
    competition = require_competition(session, code)
    if not has_standings(session, code):
        # The contract's `UpstreamUnavailable` example, almost word for word: not "no such table",
        # but "no table has ever been ingested for this competition".
        raise DataNotAvailable(
            f"No standings have been ingested for {code} yet.",
            details={"competition": code},
        )
    target_season = season if season is not None else competition.current_season
    if target_season is None:
        raise NotFound(
            f"No season is known for {code} yet: ingestion has not stored a current season for it.",
            details={"competition": code},
        )

    snapshot_date = _snapshot_date(session, code=code, season=target_season, on_or_before=snapshot)
    if snapshot_date is None:
        when = f" on or before {snapshot.isoformat()}" if snapshot else ""
        raise NotFound(
            f"No league table has been stored for {code} season {target_season}{when}.",
            details={
                "competition": code,
                "season": target_season,
                "snapshot": snapshot.isoformat() if snapshot else None,
            },
        )

    stored = _table_rows(session, code=code, season=target_season, snapshot_date=snapshot_date, matchday=matchday)
    if not stored:
        raise NotFound(
            f"The stored {code} table for {snapshot_date.isoformat()} does not describe matchday {matchday}.",
            details={"competition": code, "season": target_season, "matchday": matchday},
        )

    teams = team_index(session)
    table = standings_table(
        code=code,
        name=competition.name,
        season=target_season,
        updated_at=max(row.updated_at for row in stored),
        rows=[standing_row(row, teams[row.team_id]) for row in stored if row.team_id in teams],
        matchday=_shared(row.matchday for row in stored),
        stage=_shared(row.stage for row in stored),
        group=_shared(row.group_label for row in stored),
        table_type="TOTAL",
    )
    return Answer(data=table, data_as_of=max(row.updated_at for row in stored))


def _snapshot_date(session: Session, *, code: str, season: int, on_or_before: date | None) -> date | None:
    query = select(func.max(Standing.snapshot_date)).where(
        Standing.competition_code == code,
        Standing.season == season,
        _TOTAL,
    )
    if on_or_before is not None:
        query = query.where(Standing.snapshot_date <= on_or_before)
    return session.scalar(query)


def _table_rows(
    session: Session, *, code: str, season: int, snapshot_date: date, matchday: int | None
) -> list[Standing]:
    filters = [
        Standing.competition_code == code,
        Standing.season == season,
        Standing.snapshot_date == snapshot_date,
        _TOTAL,
    ]
    if matchday is not None:
        filters.append(Standing.matchday == matchday)
    # Grouped tables, if they ever appear, come out group by group rather than interleaved.
    return list(session.scalars(select(Standing).where(*filters).order_by(Standing.group_label, Standing.position)))


def _shared(values) -> object | None:
    """The one value they all share, or None when they disagree (or there is nothing to share)."""
    distinct = {value for value in values}
    return distinct.pop() if len(distinct) == 1 else None
