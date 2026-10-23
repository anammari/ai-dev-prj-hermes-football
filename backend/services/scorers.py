"""Top-scorer snapshots (`/competitions/{code}/top-scorers`).

The provider publishes a scorer table as a snapshot, and M2 stores one row per competition, season,
snapshot date and player. The endpoint serves the newest snapshot for the season, ordered by goals and
then assists, so "who is top scorer" is a stored fact rather than a guess. A snapshot date carries no
provider timestamp; `data_as_of` is that date at midnight UTC, which is the precision the data has.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.errors import DataNotAvailable, NotFound
from backend.schemas import top_scorer, top_scorers_table
from backend.services import Answer
from backend.services.catalog import require_competition
from db.models import Player, Team, TopScorer


def get_top_scorers(
    session: Session,
    code: str,
    *,
    season: int | None = None,
    snapshot: date | None = None,
    limit: int = 10,
) -> Answer:
    competition = require_competition(session, code)
    target_season = season if season is not None else competition.current_season
    if target_season is None:
        raise NotFound(
            f"No season is known for {code} yet: ingestion has not stored a current season for it.",
            details={"competition": code},
        )

    query = select(func.max(TopScorer.snapshot_date)).where(
        TopScorer.competition_code == code,
        TopScorer.season == target_season,
    )
    if snapshot is not None:
        query = query.where(TopScorer.snapshot_date <= snapshot)
    snapshot_date = session.scalar(query)
    if snapshot_date is None:
        when = f" on or before {snapshot.isoformat()}" if snapshot else ""
        raise DataNotAvailable(
            f"No scorer snapshot has been ingested for {code} season {target_season}{when} yet.",
            details={"competition": code, "season": target_season},
        )

    rows = session.execute(
        select(TopScorer, Player, Team)
        .join(Player, Player.id == TopScorer.player_id)
        .join(Team, Team.id == TopScorer.team_id)
        .where(
            TopScorer.competition_code == code,
            TopScorer.season == target_season,
            TopScorer.snapshot_date == snapshot_date,
        )
        .order_by(
            func.coalesce(TopScorer.goals, 0).desc(),
            func.coalesce(TopScorer.assists, 0).desc(),
            Player.name,
        )
        .limit(limit)
    ).all()
    if not rows:
        raise DataNotAvailable(
            f"The stored {code} scorer snapshot for {snapshot_date.isoformat()} has no rows.",
            details={"competition": code, "season": target_season, "snapshot": snapshot_date.isoformat()},
        )

    return Answer(
        data=top_scorers_table(
            code=code,
            name=competition.name,
            season=target_season,
            snapshot=snapshot_date,
            scorers=[top_scorer(row, player, team) for row, player, team in rows],
        ),
        data_as_of=datetime.combine(snapshot_date, time.min, tzinfo=UTC),
    )
