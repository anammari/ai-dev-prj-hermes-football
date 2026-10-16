"""Team profiles and recent form.

Form is computed here rather than left to the model, for the same reason as head-to-head: "how are
they doing" is a counting question, and counting belongs in code (`_docs/scoping.md` section 4). The
window is the last N **settled** matches, so a caller can never be told about a fixture.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.errors import NotFound
from backend.meta import as_utc
from backend.schemas import score_line, team_detail, team_summary
from backend.services import Answer
from backend.services.catalog import competition_index, competitions_of, squad_size, team_index
from backend.services.matches import _SETTLED
from db.models import Match, Team

POINTS_FOR_WIN = 3
POINTS_FOR_DRAW = 1


def get_team(session: Session, team_id: int) -> Answer:
    team = session.get(Team, team_id)
    if team is None:
        raise NotFound(f"Team {team_id} has not been ingested.", details={"team": team_id})
    data = team_detail(
        team,
        competitions=competitions_of(session, team_id),
        squad_size=squad_size(session, team_id),
    )
    return Answer(data=data, data_as_of=None)


def get_team_form(session: Session, team_id: int, *, competition: str | None = None, last: int = 5) -> Answer:
    team = session.get(Team, team_id)
    if team is None:
        raise NotFound(f"Team {team_id} has not been ingested.", details={"team": team_id})

    filters = [_SETTLED, or_(Match.home_team_id == team_id, Match.away_team_id == team_id)]
    if competition is not None:
        filters.append(Match.competition_code == competition)
    rows = list(
        session.scalars(select(Match).where(*filters).order_by(Match.utc_date.desc(), Match.id.desc()).limit(last))
    )

    teams = team_index(session)
    competitions = competition_index(session)
    played = []
    for row in rows:
        at_home = row.home_team_id == team_id
        opponent_id = row.away_team_id if at_home else row.home_team_id
        opponent = teams.get(opponent_id)
        if opponent is None:
            continue
        scored = (row.score_full_time_home if at_home else row.score_full_time_away) or 0
        conceded = (row.score_full_time_away if at_home else row.score_full_time_home) or 0
        known = competitions.get(row.competition_code)
        played.append(
            {
                "match_id": row.id,
                "utc_date": as_utc(row.utc_date),
                "competition": known.name if known else row.competition_code,
                "opponent": team_summary(opponent),
                "home": at_home,
                "result": _result(scored, conceded),
                "score": score_line(row.score_full_time_home, row.score_full_time_away),
                "_scored": scored,
                "_conceded": conceded,
            }
        )

    summary = _summary(played)
    for entry in played:
        entry.pop("_scored", None)
        entry.pop("_conceded", None)

    return Answer(
        data={
            "team": team_summary(team),
            **(
                {"competition": {"code": competition, "name": competitions[competition].name}}
                if competition and competition in competitions
                else {}
            ),
            "window": {
                "matches_considered": len(played),
                **{
                    key: value
                    for key, value in {
                        "from": as_utc(rows[-1].utc_date) if rows else None,
                        "to": as_utc(rows[0].utc_date) if rows else None,
                    }.items()
                    if value is not None
                },
            },
            "summary": summary,
            "matches": played,
        },
        data_as_of=max((row.last_updated for row in rows if row.last_updated is not None), default=None),
    )


def _result(scored: int, conceded: int) -> str:
    if scored > conceded:
        return "W"
    if scored < conceded:
        return "L"
    return "D"


def _summary(played: list[dict]) -> dict:
    won = sum(1 for entry in played if entry["result"] == "W")
    drawn = sum(1 for entry in played if entry["result"] == "D")
    lost = sum(1 for entry in played if entry["result"] == "L")
    return {
        "played": len(played),
        "won": won,
        "drawn": drawn,
        "lost": lost,
        "points": won * POINTS_FOR_WIN + drawn * POINTS_FOR_DRAW,
        "goals_for": sum(entry["_scored"] for entry in played),
        "goals_against": sum(entry["_conceded"] for entry in played),
        "clean_sheets": sum(1 for entry in played if entry["_conceded"] == 0),
    }
