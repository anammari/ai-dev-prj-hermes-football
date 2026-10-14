"""Catalog reads: competitions, and the lookups everything else needs.

`require_competition` is where the contract's `503` gets its meaning. A code the contract does not
list is rejected as `400 invalid_parameter` before it reaches here (the enum is the allowlist, and
`backend/contract.py` enforces it); a code the contract *does* list but which has never been ingested
is `503 data_not_available` - the honest "no data", and never "no matches" (`openapi.yaml`, the
`UpstreamUnavailable` response).

`has_standings` and `has_matches` draw the line between that and `404`. The contract's `NotFound` is
"the requested resource is not in the database" (the season, or the snapshot, or the match), while
`UpstreamUnavailable` is "not in the database **yet**", with the example message this API now emits
verbatim: *no standings have been ingested for this competition yet*. A competition that was fetched
into the catalog but whose tables were never stored is the second case; a season that was skipped
while other seasons are present is the first.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.errors import DataNotAvailable
from db.models import Competition, IngestRun, Match, Standing, Team, TeamCompetition


def list_competitions(session: Session) -> list[Competition]:
    """Every competition ingestion has stored, in code order so a response is reproducible."""
    return list(session.scalars(select(Competition).order_by(Competition.code)))


def require_competition(session: Session, code: str) -> Competition:
    competition = session.get(Competition, code)
    if competition is None:
        raise DataNotAvailable(
            f"{code} is not in this deployment's data: nothing has been ingested for it yet, and this "
            f"API serves the local store rather than calling the provider.",
            details={"competition": code},
        )
    return competition


def team_index(session: Session) -> dict[int, Team]:
    """All teams by id. One query beats a join per match row on a 360-team database."""
    return {team.id: team for team in session.scalars(select(Team))}


def has_standings(session: Session, code: str) -> bool:
    """Whether any table at all has been stored for this competition, in any season."""
    return bool(
        session.scalar(select(func.count()).select_from(Standing).where(Standing.competition_code == code))
    )


def has_matches(session: Session, code: str) -> bool:
    """Whether any fixture at all has been stored for this competition, in any season."""
    return bool(session.scalar(select(func.count()).select_from(Match).where(Match.competition_code == code)))


def competition_index(session: Session) -> dict[str, Competition]:
    return {row.code: row for row in session.scalars(select(Competition))}


def latest_data_as_of(session: Session) -> datetime | None:
    """The freshest upstream timestamp this response can honestly quote.

    The provider's own `lastUpdated` stamp wins, because that is the number rule 2 has an answer
    quote; before anything has been stamped, the newest run that did not fail is the best statement
    about when we last refreshed.
    """
    stamped = session.scalar(select(func.max(Match.last_updated)))
    if stamped is not None:
        return stamped
    return session.scalar(
        select(func.max(IngestRun.finished_at)).where(IngestRun.status != "failed", IngestRun.finished_at.is_not(None))
    )


def squad_size(session: Session, team_id: int) -> int:
    from db.models import Player

    return int(session.scalar(select(func.count()).select_from(Player).where(Player.team_id == team_id)) or 0)


def competitions_of(session: Session, team_id: int) -> list[Competition]:
    return list(
        session.scalars(
            select(Competition)
            .join(TeamCompetition, TeamCompetition.competition_code == Competition.code)
            .where(TeamCompetition.team_id == team_id)
            .order_by(Competition.code)
        )
    )
