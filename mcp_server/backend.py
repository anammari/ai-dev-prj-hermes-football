"""A read-only HTTP client for the M3 backend.

This is the MCP server's only data path. It holds a bearer token for the backend and issues GETs; it
never writes, never builds SQL and never reaches upstream (`AGENTS.md` rules 3 and 4). Every result
keeps the backend's `meta.data_as_of`, because the tool output has to carry freshness (`R-F4.2`).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

#: How long the MCP server waits for the backend. A knowledge search embeds the query on local CPU
#: and was measured at 13-18.5 s on the retained stack; the old 15 s budget made that endpoint a coin
#: flip (S16 recorded 9-11 s, and the corpus/load has grown since). The three budgets must nest: the
#: embedding call is innermost, then this HTTP wait, then the gateway's MCP wait. The ordering is
#: asserted in `tests/test_timeout_budget.py`, so one number cannot drift out of place unnoticed.
DEFAULT_BACKEND_TIMEOUT = 45.0


class BackendError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Envelope:
    data: object
    meta: dict


class Backend:
    def __init__(self, base_url: str, token: str | None, timeout: float = DEFAULT_BACKEND_TIMEOUT) -> None:
        if not token:
            raise BackendError("API_AGENT_TOKEN is unset: the tool server refuses to call an open API")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict | None = None) -> Envelope:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as error:
            raise BackendError(f"backend request failed: {error}") from error
        if response.status_code != 200:
            detail = ""
            try:
                body = response.json()
                detail = body.get("error", {}).get("message") or body.get("detail") or ""
            except ValueError:
                detail = response.text[:200]
            raise BackendError(f"backend HTTP {response.status_code}: {detail}", status=response.status_code)
        try:
            body = response.json()
        except ValueError as error:
            raise BackendError("backend answered a non-JSON body") from error
        if not isinstance(body, dict):
            raise BackendError("backend answered a non-object body")
        return Envelope(data=body.get("data"), meta=body.get("meta") or {})

    def competitions(self) -> list[dict]:
        return list(self._get("/competitions").data or [])

    def standings(self, code: str) -> Envelope:
        return self._get(f"/competitions/{code}/standings")

    def matches(self, code: str, **params: object) -> Envelope:
        query = {key: value for key, value in params.items() if value is not None}
        return self._get(f"/competitions/{code}/matches", query)

    def top_scorers(self, code: str, *, season: int | None = None, limit: int = 10) -> Envelope:
        params = {"limit": limit}
        if season:
            params["season"] = season
        return self._get(f"/competitions/{code}/top-scorers", params)

    def match(self, match_id: int) -> Envelope:
        return self._get(f"/matches/{match_id}")

    def team_form(self, team_id: int, *, competition: str | None = None, last: int = 5) -> Envelope:
        params = {"last": last}
        if competition:
            params["competition"] = competition
        return self._get(f"/teams/{team_id}/form", params)

    def head_to_head(self, team_a: int, team_b: int, *, limit: int = 5) -> Envelope:
        return self._get("/head-to-head", {"teamA": team_a, "teamB": team_b, "limit": limit})

    def search_knowledge(self, query: str, *, k: int = 3, min_score: float = 0.25) -> Envelope:
        return self._get("/search/knowledge", {"q": query, "k": k, "minScore": min_score})

    def freshness(self) -> dict:
        try:
            response = self._client.get("/meta/freshness")
        except httpx.HTTPError as error:
            raise BackendError(f"backend request failed: {error}") from error
        if response.status_code != 200:
            raise BackendError(f"backend HTTP {response.status_code}", status=response.status_code)
        body = response.json()
        if not isinstance(body, dict):
            raise BackendError("freshness answered a non-object body")
        return body
