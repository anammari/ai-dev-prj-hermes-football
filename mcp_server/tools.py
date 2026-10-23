"""The seven read-only tools and their compact output.

Tool outputs are deliberately small (top-N rows, no raw payloads) and always carry the backend's
`data_as_of` when the data is upstream fact (`R-F4.2`). The tools accept the user's message as a `query`
and resolve team/competition names themselves, so the model's only routing job is choosing the tool.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from mcp_server.backend import Backend, BackendError
from mcp_server.resolver import Competition, RegistryCache, Team, normalise

FINISHED = {"FINISHED", "AWARDED"}
PLAYER_STOPWORDS = {
    "how", "many", "goals", "goal", "scored", "score", "scorer", "scorers", "top", "this", "the",
    "season", "league", "has", "have", "who", "what", "which", "most", "does", "did", "and", "for",
    "with", "from", "current", "campaign", "please", "numbers", "tally", "so", "far",
}


@dataclass
class ToolContext:
    backend: Backend
    cache: RegistryCache = field(init=False)

    def __post_init__(self) -> None:
        self.cache = RegistryCache(self.backend)


def _as_of(meta: dict | None) -> str | None:
    return (meta or {}).get("data_as_of")


def _utc(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _match(match: dict) -> dict:
    score = match.get("score") or {}
    full_time = score.get("full_time") or {}
    competition = match.get("competition")
    home = match.get("home_team")
    away = match.get("away_team")
    return {
        "id": match.get("id"),
        "utc_date": match.get("utc_date"),
        "status": match.get("status"),
        "competition": competition.get("name") if isinstance(competition, dict) else competition,
        "home": home.get("name") if isinstance(home, dict) else home,
        "away": away.get("name") if isinstance(away, dict) else away,
        "home_goals": full_time.get("home"),
        "away_goals": full_time.get("away"),
        "last_updated": match.get("last_updated"),
    }


def _form_match(match: dict) -> dict:
    opponent = match.get("opponent")
    score = match.get("score") or {}
    return {
        "match_id": match.get("match_id"),
        "utc_date": match.get("utc_date"),
        "competition": match.get("competition"),
        "opponent": opponent.get("name") if isinstance(opponent, dict) else opponent,
        "home": match.get("home"),
        "result": match.get("result"),
        "score": {"home": score.get("home"), "away": score.get("away")},
    }


def _team(team: Team) -> dict:
    return {
        "id": team.id,
        "name": team.name,
        "competition": team.competition_name,
        "competition_code": team.competition_code,
    }


def _missing(message: str) -> dict:
    return {"error": "not_found", "message": message}


def _competition_for(ctx: ToolContext, query: str, team: Team | None, explicit: str | None) -> Competition | None:
    registry = ctx.cache.get()
    if explicit:
        return next((item for item in registry.competitions if item.code.lower() == explicit.lower()), None)
    found = registry.find_competition(query)
    if found is not None:
        return found
    if team is not None:
        return registry.team_competition(team.id)
    return None


def get_standings(
    ctx: ToolContext,
    query: str,
    *,
    team: str | None = None,
    competition: str | None = None,
    limit: int = 10,
) -> dict:
    registry = ctx.cache.get()
    team_ref = registry.find_team(team or query)
    comp = _competition_for(ctx, query, team_ref, competition)
    if comp is None:
        return _missing("I could not tell which team or competition you mean.")
    envelope = ctx.backend.standings(comp.code)
    table = envelope.data or {}
    rows = list(table.get("table") or [])
    focus = None
    if team_ref is not None:
        focus = next((row for row in rows if (row.get("team") or {}).get("id") == team_ref.id), None)
    top = rows[: max(1, min(limit, 20))]
    if focus is not None and focus not in top:
        top = [*top, focus]
    compact = [
        {
            "position": row.get("position"),
            "team": (row.get("team") or {}).get("name"),
            "played": row.get("played"),
            "points": row.get("points"),
            "goal_difference": row.get("goal_difference"),
            "form": row.get("form"),
        }
        for row in top
    ]
    return {
        "competition": {"code": comp.code, "name": comp.name},
        "season": table.get("season"),
        "data_as_of": _as_of(envelope.meta),
        "rows": compact,
        "focus": next((row for row in compact if team_ref is not None and row["team"] == team_ref.name), None),
    }


def get_fixtures(
    ctx: ToolContext,
    query: str,
    *,
    team: str | None = None,
    competition: str | None = None,
    limit: int = 5,
) -> dict:
    registry = ctx.cache.get()
    if team:
        team_ref = registry.find_team(team)
        if team_ref is None:
            return _missing(f"I could not find {team}.")
    else:
        teams = registry.find_teams(query, limit=2)
        team_ref = teams[0] if teams else None
    comp = _competition_for(ctx, query, team_ref, competition)
    if comp is None:
        return _missing("I could not tell which team or competition you mean.")
    params: dict = {"dateFrom": datetime.now(UTC).date().isoformat(), "limit": 200}
    if team_ref is not None:
        params["teamId"] = team_ref.id
    envelope = ctx.backend.matches(comp.code, **params)
    now = datetime.now(UTC)
    upcoming = [
        match
        for match in (envelope.data or [])
        if match.get("status") not in FINISHED and (_utc(match.get("utc_date")) or now) >= now
    ]
    teams = registry.find_teams(query, limit=2) if not team else ([team_ref] if team_ref else [])
    if len(teams) == 2:
        pair = {teams[0].id, teams[1].id}
        upcoming = [
            match
            for match in upcoming
            if {((match.get("home_team") or {}).get("id")), ((match.get("away_team") or {}).get("id"))} == pair
        ]
    return {
        "competition": {"code": comp.code, "name": comp.name},
        "data_as_of": _as_of(envelope.meta),
        "matches": [_match(match) for match in upcoming[: max(1, min(limit, 20))]],
    }


def get_match_result(ctx: ToolContext, query: str, *, team: str | None = None, match_id: int | None = None) -> dict:
    if match_id is not None:
        envelope = ctx.backend.match(match_id)
        return {"data_as_of": _as_of(envelope.meta), "match": _match(envelope.data or {})}

    registry = ctx.cache.get()
    team_ref = registry.find_team(team or query)
    if team_ref is None:
        return _missing("I could not tell which team you mean.")
    comp = _competition_for(ctx, query, team_ref, None)
    if comp is None:
        return _missing(f"I do not have a competition for {team_ref.name}.")
    envelope = ctx.backend.matches(comp.code, teamId=team_ref.id, limit=200)
    finished = [match for match in (envelope.data or []) if match.get("status") in FINISHED]
    finished.sort(key=lambda match: str(match.get("utc_date") or ""), reverse=True)
    if not finished:
        return _missing(f"I have no finished match for {team_ref.name}.")
    return {
        "team": _team(team_ref),
        "data_as_of": _as_of(envelope.meta),
        "match": _match(finished[0]),
    }


def get_team_form(ctx: ToolContext, query: str, *, team: str | None = None, last: int = 5) -> dict:
    registry = ctx.cache.get()
    team_ref = registry.find_team(team or query)
    if team_ref is None:
        return _missing("I could not tell which team you mean.")
    comp = _competition_for(ctx, query, team_ref, None)
    envelope = ctx.backend.team_form(team_ref.id, competition=comp.code if comp else None, last=last)
    data = envelope.data or {}
    return {
        "team": _team(team_ref),
        "data_as_of": _as_of(envelope.meta),
        "window": data.get("window"),
        "summary": data.get("summary"),
        "matches": [_form_match(match) for match in (data.get("matches") or [])[:last]],
    }


def get_head_to_head(ctx: ToolContext, query: str, *, limit: int = 5) -> dict:
    registry = ctx.cache.get()
    teams = registry.find_teams(query, limit=2)
    if len(teams) < 2:
        return _missing("I could not tell which two teams you mean.")
    envelope = ctx.backend.head_to_head(teams[0].id, teams[1].id, limit=limit)
    data = envelope.data or {}
    return {
        "teams": [_team(teams[0]), _team(teams[1])],
        "data_as_of": _as_of(envelope.meta),
        "summary": data.get("summary"),
        "matches": [_match(match) for match in (data.get("matches") or [])[:limit]],
    }


def _player_tokens(query: str) -> list[str]:
    return [
        token
        for token in normalise(query).split()
        if len(token) > 3 and token not in PLAYER_STOPWORDS
    ]


def _find_scorer_competition(ctx: ToolContext, query: str) -> tuple[Competition, dict, dict] | None:
    """A scorer question often names the player, not the competition.

    Walk the stored competitions and match the player's name. Thirteen local backend calls, not
    upstream calls; the first match wins. No competition named and no player matched stays a clarify.
    """
    tokens = _player_tokens(query)
    if not tokens:
        return None
    registry = ctx.cache.get()
    matches: list[tuple[Competition, dict, dict, int]] = []
    for competition in registry.competitions:
        try:
            envelope = ctx.backend.top_scorers(competition.code, limit=50)
        except BackendError:
            continue
        data = envelope.data or {}
        for row in data.get("scorers") or []:
            name = normalise(((row.get("player") or {}).get("name")) or "")
            if any(token in name.split() for token in tokens):
                matches.append((competition, data, envelope.meta, int(row.get("goals") or 0)))
                break
    if not matches:
        return None
    # A player appears in both a domestic league and a cup. Prefer the league; then the bigger tally.
    matches.sort(key=lambda item: (item[0].type != "LEAGUE", -item[3]))
    competition, data, meta, _goals = matches[0]
    return competition, data, meta


def get_top_scorers(ctx: ToolContext, query: str, *, competition: str | None = None, limit: int = 10) -> dict:
    comp = _competition_for(ctx, query, None, competition)
    if comp is None:
        found = _find_scorer_competition(ctx, query)
        if found is None:
            return _missing("I could not tell which competition or player you mean.")
        comp, data, meta = found
        return {
            "competition": data.get("competition") or {"code": comp.code, "name": comp.name},
            "season": data.get("season"),
            "snapshot": data.get("snapshot"),
            "data_as_of": _as_of(meta),
            "scorers": (data.get("scorers") or [])[:limit],
        }
    envelope = ctx.backend.top_scorers(comp.code, limit=limit)
    data = envelope.data or {}
    return {
        "competition": data.get("competition") or {"code": comp.code, "name": comp.name},
        "season": data.get("season"),
        "snapshot": data.get("snapshot"),
        "data_as_of": _as_of(envelope.meta),
        "scorers": [
            {
                "player": row.get("player"),
                "team": row.get("team"),
                "goals": row.get("goals"),
                "assists": row.get("assists"),
                "penalties": row.get("penalties"),
                "played": row.get("played"),
            }
            for row in (data.get("scorers") or [])
        ],
    }


def search_knowledge(ctx: ToolContext, query: str, *, k: int = 3) -> dict:
    envelope = ctx.backend.search_knowledge(query, k=k)
    hits = []
    for hit in envelope.data or []:
        hits.append(
            {
                "source_file": hit.get("source_file"),
                "heading": hit.get("heading"),
                "score": hit.get("score"),
                "snippet": hit.get("snippet"),
            }
        )
    return {"query": query, "data_as_of": None, "hits": hits, "count": len(hits)}


def get_data_freshness(ctx: ToolContext, query: str = "", *, competition: str | None = None) -> dict:
    report = ctx.backend.freshness()
    rows = list(report.get("competitions") or [])
    if competition:
        rows = [row for row in rows if str(row.get("code", "")).lower() == competition.lower()]
    elif query:
        found = ctx.cache.get().find_competition(query)
        if found is not None:
            rows = [row for row in rows if row.get("code") == found.code]
    return {
        "as_of": report.get("as_of"),
        "competitions": [
            {
                "code": row.get("code"),
                "name": row.get("name"),
                "status": row.get("status"),
                "last_success_at": row.get("last_success_at"),
                "age_minutes": row.get("age_minutes"),
            }
            for row in rows
        ],
    }


Handler = Callable[..., dict]

TOOLS: dict[str, tuple[str, dict, Handler]] = {
    "get_standings": (
        "League table: position, points and goal difference for a named team or competition.",
        {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user's message; team and competition are read from it.",
                },
                "team": {"type": "string"},
                "competition": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
            },
            "required": ["query"],
        },
        get_standings,
    ),
    "get_fixtures": (
        "Upcoming match dates and kick-off times for a team or competition.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "team": {"type": "string"},
                "competition": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["query"],
        },
        get_fixtures,
    ),
    "get_match_result": (
        "The score and status of a played match, by team or by match id.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "team": {"type": "string"},
                "match_id": {"type": "integer"},
            },
            "required": ["query"],
        },
        get_match_result,
    ),
    "get_team_form": (
        "A team's recent results and form.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "team": {"type": "string"},
                "last": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["query"],
        },
        get_team_form,
    ),
    "get_head_to_head": (
        "Results and win counts between two teams named in the message.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["query"],
        },
        get_head_to_head,
    ),
    "get_top_scorers": (
        "Top scorers for a competition: goals, assists and penalties from the latest stored snapshot.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "competition": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
            "required": ["query"],
        },
        get_top_scorers,
    ),
    "search_knowledge": (
        "The hand-written notes: competition rules, tiebreakers, definitions and policy, with a citation.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
            },
            "required": ["query"],
        },
        search_knowledge,
    ),
    "get_data_freshness": (
        "How old the stored data is and when it was last refreshed.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}, "competition": {"type": "string"}},
        },
        get_data_freshness,
    ),
}


def call(ctx: ToolContext, name: str, arguments: dict) -> dict:
    if name not in TOOLS:
        raise ValueError(f"unknown tool {name!r}")
    _description, schema, handler = TOOLS[name]
    allowed = set(schema.get("properties", {}))
    unknown = set(arguments) - allowed
    if unknown:
        raise ValueError(f"unknown arguments for {name}: {sorted(unknown)}")
    try:
        return handler(ctx, **arguments)
    except BackendError as error:
        raise error
