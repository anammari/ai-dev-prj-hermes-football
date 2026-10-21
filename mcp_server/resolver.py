"""Resolve team and competition names from a user message to backend ids.

This is *argument resolution*, not routing: the model has already chosen a tool. The registry is built
once from the competitions and their stored tables, so a short club name ("Spurs", "Man City") maps to
the provider's team id and the competition the table is in. Nothing here calls a model and nothing here
touches the router.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass

from mcp_server.backend import Backend, BackendError

SUFFIXES = {"fc", "afc", "cf", "sc", "ac", "club", "the", "de", "do", "da"}
STOPWORDS = SUFFIXES | {"football", "soccer"}

#: Common fan names that are not substrings of the provider's name.
TEAM_ALIASES = {
    "spurs": "tottenham hotspur",
    "man utd": "manchester united",
    "man united": "manchester united",
    "man city": "manchester city",
    "wolves": "wolverhampton",
    "forest": "nottingham forest",
    "villa": "aston villa",
    "dortmund": "borussia dortmund",
    "bayern": "bayern munchen",
    "gladbach": "monchengladbach",
    "atleti": "atletico madrid",
    "barca": "barcelona",
}

COMPETITION_ALIASES = {
    "PL": ("premier league", "epl", "english premier league"),
    "PD": ("la liga", "laliga", "primera division", "spanish league"),
    "SA": ("serie a", "italian league"),
    "BL1": ("bundesliga", "german league"),
    "FL1": ("ligue 1", "french league"),
    "ELC": ("championship", "efl championship", "english championship"),
    "CL": ("champions league", "ucl"),
    "CLI": ("copa libertadores", "libertadores"),
    "BSA": ("brasileirao", "brazilian serie a", "campeonato brasileiro"),
    "DED": ("eredivisie", "dutch league"),
    "PPL": ("primeira liga", "portuguese league"),
    "EC": ("european championship", "euro 2024", "euro"),
    "WC": ("world cup",),
}


def normalise(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    ascii_text = ascii_text.lower().replace("&", " and ")
    ascii_text = re.sub(r"[^a-z0-9]+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token for token in normalise(text).split() if token not in STOPWORDS)


def _apply_aliases(text: str) -> str:
    result = text
    for alias, canonical in sorted(TEAM_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        result = re.sub(rf"\b{re.escape(alias)}\b", canonical, result)
    return result


@dataclass(frozen=True)
class Team:
    id: int
    name: str
    competition_code: str
    competition_name: str
    competition_type: str


@dataclass(frozen=True)
class Competition:
    code: str
    name: str
    type: str


class Registry:
    def __init__(self, competitions: list[Competition], teams: list[Team]) -> None:
        self.competitions = tuple(competitions)
        self.teams = tuple(teams)

    @classmethod
    def load(cls, backend: Backend) -> Registry:
        competitions: list[Competition] = []
        teams: list[Team] = []
        for row in backend.competitions():
            try:
                competition = Competition(
                    code=str(row["code"]),
                    name=str(row.get("name") or row["code"]),
                    type=str(row.get("type") or "LEAGUE"),
                )
            except (KeyError, TypeError):
                continue
            competitions.append(competition)
            try:
                table = backend.standings(competition.code).data or {}
            except BackendError:
                continue
            for entry in table.get("table", []) if isinstance(table, dict) else []:
                team = entry.get("team") or {}
                if "id" not in team:
                    continue
                teams.append(
                    Team(
                        id=int(team["id"]),
                        name=str(team.get("name") or team["id"]),
                        competition_code=competition.code,
                        competition_name=competition.name,
                        competition_type=competition.type,
                    )
                )
        return cls(competitions, teams)

    def find_competition(self, text: str) -> Competition | None:
        query = f" {normalise(text)} "
        best: tuple[int, Competition] | None = None
        for competition in self.competitions:
            phrases = COMPETITION_ALIASES.get(competition.code, ())
            candidates = [*phrases, normalise(competition.name), competition.code.lower()]
            for phrase in candidates:
                phrase = normalise(phrase)
                if phrase and f" {phrase} " in query:
                    score = len(phrase.split())
                    if best is None or score > best[0]:
                        best = (score, competition)
        return best[1] if best else None

    def _candidates(self, text: str) -> list[tuple[int, int, Team]]:
        raw = f" {_apply_aliases(normalise(text))} "
        query_tokens = set(raw.split())
        found: list[tuple[int, int, Team]] = []
        for team in self.teams:
            name_tokens = _tokens(team.name)
            if not name_tokens:
                continue
            phrase = " ".join(name_tokens)
            score = 0
            if f" {phrase} " in raw:
                score += 10 + len(name_tokens)
            elif len(name_tokens) >= 2 and set(name_tokens) <= query_tokens:
                score += 4 + len(name_tokens)
            elif len(name_tokens) == 1 and name_tokens[0] in query_tokens:
                score += 3
            if score:
                position = raw.find(name_tokens[0]) if name_tokens[0] in raw else 10_000
                found.append((score, -position, team))
        return found

    def find_team(self, text: str, *, competition: Competition | None = None) -> Team | None:
        candidates = self._candidates(text)
        if competition is not None:
            candidates = [item for item in candidates if item[2].competition_code == competition.code]
        if not candidates:
            return None
        best_score = max(item[0] for item in candidates)
        best = [item for item in candidates if item[0] == best_score]
        if len(best) > 1:
            best.sort(key=lambda item: (item[2].competition_type != "LEAGUE", item[2].name))
        return best[0][2]

    def find_teams(self, text: str, *, limit: int = 2) -> list[Team]:
        candidates = sorted(self._candidates(text), key=lambda item: (item[1], -item[0]))
        chosen: list[Team] = []
        seen: set[int] = set()
        for _score, _position, team in candidates:
            if team.id in seen:
                continue
            seen.add(team.id)
            chosen.append(team)
            if len(chosen) == limit:
                break
        return chosen

    def team_competition(self, team_id: int) -> Competition | None:
        rows = [team for team in self.teams if team.id == team_id]
        if not rows:
            return None
        rows.sort(key=lambda team: (team.competition_type != "LEAGUE", team.competition_name))
        code = rows[0].competition_code
        return next((competition for competition in self.competitions if competition.code == code), None)


class RegistryCache:
    """Build the registry lazily and reuse it for a few minutes; the tables change once a day."""

    def __init__(self, backend: Backend, ttl_seconds: float = 600.0) -> None:
        self._backend = backend
        self._ttl = ttl_seconds
        self._registry: Registry | None = None
        self._built_at = 0.0
        self._lock = threading.Lock()

    def get(self) -> Registry:
        with self._lock:
            if self._registry is None or time.monotonic() - self._built_at > self._ttl:
                self._registry = Registry.load(self._backend)
                self._built_at = time.monotonic()
            return self._registry
