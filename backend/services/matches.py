"""Fixtures, results, one match, and the head-to-head the provider gets wrong.

The head-to-head aggregate is computed here rather than read from upstream, and the contract says
why: on the probed key the provider reported `numberOfMatches: 3` while returning zeroed wins, draws
and losses for both teams. Counting in code is also what keeps the arithmetic out of the model
(`R-F4.2`) - and it is why `summary` covers every meeting in the window while `matches` carries only
the most recent few.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend.errors import DataNotAvailable, InvalidParameter, NotFound
from backend.meta import as_utc
from backend.schemas import match as match_payload
from backend.schemas import team_summary
from backend.services import Answer, Page
from backend.services.catalog import competition_index, has_matches, require_competition, team_index
from db.models import Match

#: A match that has a result to count. A scheduled fixture is not a result, and a scoreless one is not
#: a score: `R-F4.2` wants the arithmetic done on settled matches only.
_SETTLED = and_(
    Match.status == "FINISHED",
    Match.score_full_time_home.is_not(None),
    Match.score_full_time_away.is_not(None),
)


def list_competition_matches(
    session: Session,
    code: str,
    *,
    season: int | None = None,
    matchday: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    team_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page:
    competition = require_competition(session, code)
    if not has_matches(session, code):
        # "Clients must report this as 'no data', never as 'no matches'" (`openapi.yaml`): an empty
        # page would be read as "this competition has no fixtures", which is not what we know.
        raise DataNotAvailable(
            f"No fixtures or results have been ingested for {code} yet.",
            details={"competition": code},
        )
    target_season = season if season is not None else competition.current_season
    filters = _filters(
        code=code,
        season=target_season,
        matchday=matchday,
        date_from=date_from,
        date_to=date_to,
        team_id=team_id,
        status=status,
    )
    total = int(session.scalar(select(func.count()).select_from(Match).where(*filters)) or 0)
    rows = list(
        session.scalars(
            select(Match).where(*filters).order_by(Match.utc_date, Match.id).limit(limit).offset(offset)
        )
    )
    return Page(data=_payloads(session, rows), total=total, data_as_of=_newest_stamp(rows))


def get_match(session: Session, match_id: int) -> Answer:
    row = session.get(Match, match_id)
    if row is None:
        raise NotFound(f"No match {match_id} has been ingested.", details={"match": match_id})
    return Answer(data=_payloads(session, [row])[0], data_as_of=row.last_updated)


def head_to_head(
    session: Session,
    team_a: int,
    team_b: int,
    *,
    limit: int = 5,
    competition: str | None = None,
) -> Answer:
    if team_a == team_b:
        raise InvalidParameter(
            "teamA and teamB must be two different teams.",
            details={"teamA": team_a, "teamB": team_b},
        )
    teams = team_index(session)
    unknown = [team for team in (team_a, team_b) if team not in teams]
    if unknown:
        raise NotFound(
            f"Team {unknown[0]} has not been ingested.",
            details={"unknown_teams": unknown},
        )

    filters = [
        _SETTLED,
        or_(
            and_(Match.home_team_id == team_a, Match.away_team_id == team_b),
            and_(Match.home_team_id == team_b, Match.away_team_id == team_a),
        ),
    ]
    if competition is not None:
        filters.append(Match.competition_code == competition)
    meetings = list(session.scalars(select(Match).where(*filters).order_by(Match.utc_date.desc(), Match.id.desc())))

    return Answer(
        data={
            "teams": [team_summary(teams[team_a]), team_summary(teams[team_b])],
            "window": {
                "matches_considered": len(meetings),
                **{
                    key: value
                    for key, value in {
                        "from": as_utc(min((row.utc_date for row in meetings), default=None)),
                        "to": as_utc(max((row.utc_date for row in meetings), default=None)),
                    }.items()
                    if value is not None
                },
            },
            "summary": _record(meetings, team_a=team_a),
            "matches": _payloads(session, meetings[:limit]),
        },
        data_as_of=_newest_stamp(meetings),
    )


def _filters(
    *,
    code: str,
    season: int | None,
    matchday: int | None,
    date_from: date | None,
    date_to: date | None,
    team_id: int | None,
    status: str | None,
) -> list:
    filters = [Match.competition_code == code]
    if season is not None:
        # The contract says an omitted season means the competition's current season, so this is a
        # filter rather than a preference: otherwise "when do they play next" could answer with a
        # fixture from two seasons ago.
        filters.append(Match.season == season)
    if matchday is not None:
        filters.append(Match.matchday == matchday)
    if date_from is not None:
        filters.append(Match.utc_date >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to is not None:
        filters.append(Match.utc_date <= datetime.combine(date_to, time.max, tzinfo=UTC))
    if team_id is not None:
        filters.append(or_(Match.home_team_id == team_id, Match.away_team_id == team_id))
    if status is not None:
        filters.append(Match.status == status)
    return filters


def _payloads(session: Session, rows: list[Match]) -> list[dict]:
    teams = team_index(session)
    competitions = competition_index(session)
    payloads = []
    for row in rows:
        home, away = teams.get(row.home_team_id), teams.get(row.away_team_id)
        if home is None or away is None:
            # The foreign keys make this unreachable on a healthy database. Skipping beats a 500, and
            # it hides nothing: the match is still reachable by its own id.
            continue
        known = competitions.get(row.competition_code)
        payloads.append(
            match_payload(row, competition_name=known.name if known else row.competition_code, home=home, away=away)
        )
    return payloads


def _record(meetings: list[Match], *, team_a: int) -> dict:
    """Wins, draws, losses and goals from team A's point of view, over every meeting given."""
    wins = draws = losses = 0
    goals_a = goals_b = 0
    for row in meetings:
        a_home = row.home_team_id == team_a
        scored_a = (row.score_full_time_home if a_home else row.score_full_time_away) or 0
        scored_b = (row.score_full_time_away if a_home else row.score_full_time_home) or 0
        goals_a += scored_a
        goals_b += scored_b
        if scored_a > scored_b:
            wins += 1
        elif scored_a < scored_b:
            losses += 1
        else:
            draws += 1
    return {
        "played": len(meetings),
        "team_a_wins": wins,
        "draws": draws,
        "team_b_wins": losses,
        "goals": {"team_a": goals_a, "team_b": goals_b},
    }


def _newest_stamp(rows: list[Match]) -> datetime | None:
    return max((row.last_updated for row in rows if row.last_updated is not None), default=None)
