"""Turn a tool payload into a short, grounded sentence.

No second model is used here. The composer only restates numbers, names and dates that the tool
returned, and it attaches the provider's data timestamp. That is the strongest form of the grounding
rule: there is no generative step that could invent a score. The knowledge branch quotes the note and
cites its file and heading.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

SOURCE = "football-data.org"


def _utc(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def _stamp(value: object) -> str:
    moment = _utc(value)
    if moment is None:
        return ""
    return f"As of {moment:%Y-%m-%d %H:%M} UTC, source: {SOURCE}."


def _date(value: object) -> str:
    moment = _utc(value)
    if moment is None:
        return str(value or "unknown date")
    return f"{moment:%a %d %b %Y, %H:%M} UTC"


def _goal_difference(value: object) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "unknown GD"
    return f"GD {number:+d}"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or singular + "s")


def _clean(text: object, limit: int = 1200) -> str:
    value = str(text or "").replace("**", "").replace("__", "")
    value = re.sub(r"(?m)^#+\s*", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > limit:
        cut = value[:limit].rfind(". ")
        value = value[: cut + 1] if cut > limit // 2 else value[: limit - 1].rstrip() + "…"
    return value


def _ordinal(value: object) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    suffix = "th" if 11 <= number % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def standings(payload: dict) -> tuple[str, bool]:
    if payload.get("error"):
        return str(payload.get("message") or "I could not find that."), False
    competition = (payload.get("competition") or {}).get("name") or "the competition"
    rows = payload.get("rows") or []
    focus = payload.get("focus")
    if focus:
        text = (
            f"{focus['team']} are {_ordinal(focus['position'])} in the {competition} with "
            f"{focus['points']} points from {focus['played']} matches ({_goal_difference(focus['goal_difference'])})."
        )
    elif rows:
        top = "; ".join(
            f"{row['position']}. {row['team']} {row['points']} pts" for row in rows[:5]
        )
        text = f"{competition} table: {top}."
    else:
        return f"I have no table for the {competition}.", False
    stamp = _stamp(payload.get("data_as_of"))
    return (f"{text} {stamp}".strip(), True)


def fixtures(payload: dict) -> tuple[str, bool]:
    if payload.get("error"):
        return str(payload.get("message") or "I could not find that."), False
    matches = payload.get("matches") or []
    stamp = _stamp(payload.get("data_as_of"))
    if not matches:
        return f"I have no upcoming matches on file for that team or competition. {stamp}".strip(), False
    lines = []
    for match in matches[:3]:
        lines.append(f"{match['home']} v {match['away']}, {_date(match.get('utc_date'))} ({match.get('status')})")
    return ("Upcoming: " + "; ".join(lines) + f". {stamp}".strip(), True)


def match_result(payload: dict) -> tuple[str, bool]:
    if payload.get("error"):
        return str(payload.get("message") or "I could not find that."), False
    match = payload.get("match") or {}
    score = ""
    if match.get("home_goals") is not None and match.get("away_goals") is not None:
        score = f"{match['home_goals']}-{match['away_goals']}"
    status = str(match.get("status", "")).lower()
    text = f"{match.get('home')} {score} {match.get('away')} ({status}, {_date(match.get('utc_date'))})."
    stamp = _stamp(payload.get("data_as_of"))
    return (f"{text} {stamp}".strip(), True)


def team_form(payload: dict) -> tuple[str, bool]:
    if payload.get("error"):
        return str(payload.get("message") or "I could not find that."), False
    team = (payload.get("team") or {}).get("name") or "The team"
    summary = payload.get("summary") or {}
    if not summary:
        return f"I have no recent form for {team}.", False
    text = (
        f"{team}'s last {summary.get('played', 0)}: {summary.get('won', 0)}W "
        f"{summary.get('drawn', 0)}D {summary.get('lost', 0)}L, {summary.get('points', 0)} points, "
        f"{summary.get('clean_sheets', 0)} clean {_plural(int(summary.get('clean_sheets', 0) or 0), 'sheet')}."
    )
    stamp = _stamp(payload.get("data_as_of"))
    return (f"{text} {stamp}".strip(), True)


def head_to_head(payload: dict) -> tuple[str, bool]:
    if payload.get("error"):
        return str(payload.get("message") or "I could not find that."), False
    teams = payload.get("teams") or []
    if len(teams) < 2:
        return "I could not tell which two teams you mean.", False
    summary = payload.get("summary") or {}
    text = (
        f"{teams[0].get('name')} and {teams[1].get('name')} have met {summary.get('played', 0)} times: "
        f"{teams[0].get('name')} {summary.get('team_a_wins', 0)} wins, {summary.get('draws', 0)} draws, "
        f"{teams[1].get('name')} {summary.get('team_b_wins', 0)} wins."
    )
    stamp = _stamp(payload.get("data_as_of"))
    return (f"{text} {stamp}".strip(), True)


def freshness(payload: dict) -> tuple[str, bool]:
    rows = payload.get("competitions") or []
    as_of = _utc(payload.get("as_of"))
    prefix = f"The newest stored data is as of {as_of:%Y-%m-%d %H:%M} UTC." if as_of else "Freshness is unknown."
    if not rows:
        return prefix, False
    parts = []
    for row in rows[:4]:
        parts.append(
            f"{row.get('name')}: {row.get('status')}, last success {_date(row.get('last_success_at'))} "
            f"({row.get('age_minutes')} minutes old)"
        )
    return prefix + " " + "; ".join(parts) + ".", True


def top_scorers(payload: dict) -> tuple[str, bool]:
    if payload.get("error"):
        return str(payload.get("message") or "I could not find that."), False
    competition = (payload.get("competition") or {}).get("name") or "the competition"
    scorers = payload.get("scorers") or []
    stamp = _stamp(payload.get("data_as_of"))
    if not scorers:
        return f"I have no scorer rows for the {competition}. {stamp}".strip(), False
    lines = []
    for index, row in enumerate(scorers[:5], start=1):
        player = (row.get("player") or {}).get("name") or "unknown player"
        team = (row.get("team") or {}).get("name") or "unknown team"
        goals = row.get("goals")
        assists = row.get("assists")
        detail = f"{goals} goals"
        if assists is not None:
            detail += f", {assists} {_plural(int(assists), 'assist')}"
        lines.append(f"{index}. {player} ({team}): {detail}")
    return (f"{competition} top scorers: " + "; ".join(lines) + f". {stamp}".strip(), True)


def knowledge(payload: dict) -> tuple[str, bool]:
    hits = payload.get("hits") or []
    if not hits:
        return (
            "I don't have a note that answers that. I can answer from stored match data "
            "or from the notes I hold.",
            False,
        )
    hit = hits[0]
    snippet = _clean(hit.get("snippet"))
    citation = f"{hit.get('source_file')}, {hit.get('heading')}"
    return f"{snippet}\n\nSource: {citation}.", True


FORMATTERS = {
    "get_standings": standings,
    "get_fixtures": fixtures,
    "get_match_result": match_result,
    "get_team_form": team_form,
    "get_head_to_head": head_to_head,
    "get_data_freshness": freshness,
    "get_top_scorers": top_scorers,
    "search_knowledge": knowledge,
}


def compose(tool: str, payload: dict) -> tuple[str, bool]:
    formatter = FORMATTERS.get(tool)
    if formatter is None:
        return "I don't have a tool for that.", False
    return formatter(payload)
