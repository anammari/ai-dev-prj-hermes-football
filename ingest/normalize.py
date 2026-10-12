"""Normalize football-data.org payloads into the serving schema."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Competition, Match, Player, Season, Standing, Team, TeamCompetition, TopScorer


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _upsert(session: Session, model: type, key: object, values: dict[str, Any], *, identity: str = "id") -> str:
    row = session.get(model, key)
    if row is None:
        session.add(model(**{identity: key, **values}))
        return "inserted"
    changed = False
    for name, value in values.items():
        if getattr(row, name) != value:
            setattr(row, name, value)
            changed = True
    return "updated" if changed else "unchanged"


def _count(counter: dict[str, int], result: str) -> None:
    counter[result] += 1


def upsert_competition(session: Session, item: dict[str, Any], counter: dict[str, int]) -> None:
    code = item.get("code")
    if not code:
        raise ValueError("upstream competition is missing its code")
    if not item.get("name"):
        raise ValueError(f"upstream competition {code} is missing its name")
    current = item.get("currentSeason") or {}
    year = _season_year(current)
    values = {
        "name": item.get("name") or code,
        "area": (item.get("area") or {}).get("name"),
        "type": item.get("type"),
        "current_season": year,
        "season_start": parse_date(current.get("startDate")),
        "season_end": parse_date(current.get("endDate")),
    }
    _count(counter, _upsert(session, Competition, code, values, identity="code"))
    if year is None:
        return
    existing = session.scalar(
        select(Season).where(Season.competition_code == code, Season.year == year)
    )
    season_values = {
        "competition_code": code,
        "year": year,
        "start_date": parse_date(current.get("startDate")),
        "end_date": parse_date(current.get("endDate")),
        "is_current": True,
    }
    if existing is None:
        session.add(Season(**season_values))
        counter["inserted"] += 1
    else:
        changed = False
        for name, value in season_values.items():
            if getattr(existing, name) != value:
                setattr(existing, name, value)
                changed = True
        counter["updated" if changed else "unchanged"] += 1


def upsert_team(
    session: Session,
    team: dict[str, Any],
    competition_code: str,
    counter: dict[str, int],
) -> None:
    team_id = team.get("id")
    if not team_id:
        raise ValueError(f"upstream team for {competition_code} is missing its id")
    if not team.get("name"):
        raise ValueError(f"upstream team {team_id} is missing its name")
    values = {
        "name": team["name"],
        "tla": team.get("tla"),
        "crest": team.get("crest"),
        "area": (team.get("area") or {}).get("name"),
        "founded": team.get("founded"),
        "venue": team.get("venue"),
        "club_colors": team.get("clubColors"),
    }
    _count(counter, _upsert(session, Team, team_id, values))
    relation_key = (team_id, competition_code)
    if session.get(TeamCompetition, relation_key) is None:
        session.add(TeamCompetition(team_id=team_id, competition_code=competition_code))
        counter["inserted"] += 1
    for player in team.get("squad") or []:
        player_id = player.get("id")
        if not player_id:
            raise ValueError(f"upstream squad entry for team {team_id} is missing its id")
        if not player.get("name"):
            raise ValueError(f"upstream player {player_id} is missing its name")
        player_values = {
            "team_id": team_id,
            "name": player["name"],
            "position": player.get("position"),
            "date_of_birth": parse_date(player.get("dateOfBirth")),
            "nationality": player.get("nationality"),
        }
        _count(counter, _upsert(session, Player, player_id, player_values))


def upsert_match(session: Session, item: dict[str, Any], counter: dict[str, int]) -> None:
    match_id = item.get("id")
    competition_code = (item.get("competition") or {}).get("code")
    home = item.get("homeTeam") or {}
    away = item.get("awayTeam") or {}
    if not match_id or not competition_code or not home.get("id") or not away.get("id"):
        raise ValueError("upstream match is missing its id, competition, or team id")
    if not item.get("status") or not item.get("utcDate"):
        raise ValueError(f"upstream match {match_id} is missing status or utcDate")
    upsert_team(session, home, competition_code, counter)
    upsert_team(session, away, competition_code, counter)
    score = item.get("score") or {}
    full_time = score.get("fullTime") or {}
    half_time = score.get("halfTime") or {}
    values = {
        "competition_code": competition_code,
        "season": _season_year(item.get("season") or {}),
        "matchday": item.get("matchday"),
        "stage": item.get("stage"),
        "status": item["status"],
        "utc_date": parse_datetime(item["utcDate"]),
        "home_team_id": home["id"],
        "away_team_id": away["id"],
        "score_winner": score.get("winner"),
        "score_duration": score.get("duration"),
        "score_full_time_home": full_time.get("home"),
        "score_full_time_away": full_time.get("away"),
        "score_half_time_home": half_time.get("home"),
        "score_half_time_away": half_time.get("away"),
        "venue": item.get("venue"),
        "referees": item.get("referees"),
        "last_updated": parse_datetime(item.get("lastUpdated")),
    }
    _count(counter, _upsert(session, Match, match_id, values))


def upsert_standings(
    session: Session,
    payload: dict[str, Any],
    snapshot_date: date,
    counter: dict[str, int],
) -> None:
    competition_code = (payload.get("competition") or {}).get("code")
    season_year = _season_year(payload.get("season") or {})
    if not competition_code or season_year is None:
        return
    for table in payload.get("standings") or []:
        table_type = table.get("type")
        for row in table.get("table") or []:
            team = row.get("team") or {}
            team_id = team.get("id")
            if not team_id:
                raise ValueError(f"upstream standings row for {competition_code} is missing its team id")
            if not row.get("position") or row.get("playedGames") is None or row.get("points") is None:
                raise ValueError(f"upstream standings row for team {team_id} is missing required totals")
            upsert_team(session, team, competition_code, counter)
            identity = select(Standing).where(
                Standing.competition_code == competition_code,
                Standing.season == season_year,
                Standing.snapshot_date == snapshot_date,
                Standing.table_type == table_type,
                Standing.team_id == team_id,
            )
            existing = session.scalar(identity)
            values = {
                "competition_code": competition_code,
                "season": season_year,
                "snapshot_date": snapshot_date,
                "matchday": table.get("matchday"),
                "stage": table.get("stage"),
                "group_label": table.get("group"),
                "table_type": table_type,
                "team_id": team_id,
                "position": row.get("position") or 0,
                "played": row.get("playedGames") or 0,
                "won": row.get("won"),
                "drawn": row.get("draw"),
                "lost": row.get("lost"),
                "goals_for": row.get("goalsFor"),
                "goals_against": row.get("goalsAgainst"),
                "goal_difference": row.get("goalDifference"),
                "points": row.get("points") or 0,
                "form": row.get("form"),
            }
            if existing is None:
                session.add(Standing(**values))
                counter["inserted"] += 1
            else:
                changed = any(getattr(existing, key) != value for key, value in values.items())
                if changed:
                    for key, value in values.items():
                        setattr(existing, key, value)
                counter["updated" if changed else "unchanged"] += 1


def upsert_scorers(
    session: Session,
    payload: dict[str, Any],
    snapshot_date: date,
    counter: dict[str, int],
) -> None:
    competition_code = (payload.get("competition") or {}).get("code")
    season_year = _season_year(payload.get("season") or {})
    if not competition_code or season_year is None:
        return
    for scorer in payload.get("scorers") or []:
        player = scorer.get("player") or {}
        team = scorer.get("team") or {}
        if not player.get("id") or not team.get("id"):
            raise ValueError(f"upstream scorer for {competition_code} is missing its player or team id")
        if not player.get("name"):
            raise ValueError(f"upstream scorer player {player['id']} is missing its name")
        upsert_team(session, team, competition_code, counter)
        player_values = {
            "team_id": team["id"],
            "name": player["name"],
            "position": player.get("position"),
            "date_of_birth": parse_date(player.get("dateOfBirth")),
            "nationality": player.get("nationality"),
        }
        _count(counter, _upsert(session, Player, player["id"], player_values))
        identity = select(TopScorer).where(
            TopScorer.competition_code == competition_code,
            TopScorer.season == season_year,
            TopScorer.snapshot_date == snapshot_date,
            TopScorer.player_id == player["id"],
        )
        existing = session.scalar(identity)
        values = {
            "competition_code": competition_code,
            "season": season_year,
            "snapshot_date": snapshot_date,
            "player_id": player["id"],
            "team_id": team["id"],
            "played_matches": scorer.get("playedMatches"),
            "goals": scorer.get("goals"),
            "assists": scorer.get("assists"),
            "penalties": scorer.get("penalties"),
        }
        if existing is None:
            session.add(TopScorer(**values))
            counter["inserted"] += 1
        else:
            changed = any(getattr(existing, key) != value for key, value in values.items())
            if changed:
                for key, value in values.items():
                    setattr(existing, key, value)
            counter["updated" if changed else "unchanged"] += 1


def _season_year(season: dict[str, Any]) -> int | None:
    year = season.get("year")
    if isinstance(year, int):
        return year
    start = parse_date(season.get("startDate"))
    return start.year if start else None
