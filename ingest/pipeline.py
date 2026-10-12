"""Daily collection from football-data.org into bronze and normalized serving tables."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from db.models import Competition, IngestRun, RawPayload, new_id
from db.session import session_scope
from db.settings import Settings
from ingest.client import DataNotAvailable, FootballDataClient, UpstreamError
from ingest.knowledge.embedding import Embedder
from ingest.knowledge.indexer import index_corpus
from ingest.normalize import (
    parse_date,
    upsert_competition,
    upsert_match,
    upsert_scorers,
    upsert_standings,
    upsert_team,
)


@dataclass(slots=True)
class RunReport:
    run_id: str
    status: str
    competitions: list[str] = field(default_factory=list)
    calls_used: int = 0
    rate_limit_hits: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_unchanged: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    duration_seconds: float = 0.0
    notes_index: dict[str, Any] = field(default_factory=dict)


def run_ingestion(
    settings: Settings,
    factory: sessionmaker[Session],
    client: FootballDataClient,
    embedder: Embedder,
    *,
    trigger: str = "manual",
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RunReport:
    if trigger not in {"manual", "schedule"}:
        raise ValueError("trigger must be 'manual' or 'schedule'")
    started = _utc(now())
    started_clock = datetime.now(UTC)
    calls_before = client.stats.calls_used
    rate_limit_hits_before = client.stats.rate_limit_hits
    run_id = new_id()
    report = RunReport(run_id=run_id, status="running")
    counter = {"inserted": 0, "updated": 0, "unchanged": 0}
    inserted_competitions: set[str | None] = set()
    with session_scope(factory) as session:
        session.add(IngestRun(id=run_id, started_at=started, status="running", trigger=trigger))

    try:
        catalog = _fetch(client, factory, run_id, "/competitions", {}, report)
        competitions = catalog.get("competitions")
        if not isinstance(competitions, list):
            raise UpstreamError("upstream competitions response is missing its list")
        for competition in competitions:
            if upsert_competition_row(factory, competition, counter):
                inserted_competitions.add(competition.get("code"))
        report.competitions = [item["code"] for item in competitions if item.get("code")]
        snapshots = [
            item
            for item in competitions
            if item.get("code") and _season_year(item.get("currentSeason") or {})
        ]
        team_details_seen: set[int] = set()

        for competition in snapshots:
            code = competition["code"]
            season = _season_year(competition.get("currentSeason") or {})
            assert season is not None
            params = {"season": season}
            try:
                teams_params = {**params, "limit": 500}
                teams = _fetch(client, factory, run_id, f"/competitions/{code}/teams", teams_params, report)
                _normalize_teams(factory, teams, code, counter)
                for team in teams.get("teams", []):
                    team_id = team.get("id")
                    if "squad" in team or not team_id or team_id in team_details_seen:
                        continue
                    team_details_seen.add(team_id)
                    try:
                        detail = _fetch(client, factory, run_id, f"/teams/{team_id}", {}, report)
                        _normalize_team_detail(factory, detail, code, counter)
                    except DataNotAvailable as exc:
                        _add_unavailable(report, "squad", str(team_id), exc)
            except DataNotAvailable as exc:
                _add_unavailable(report, "teams", code, exc)

            for resource, normalizer in (
                ("standings", upsert_standings),
                ("scorers", upsert_scorers),
            ):
                try:
                    resource_params = {**params, **({"limit": 500} if resource == "scorers" else {})}
                    payload = _fetch(
                        client, factory, run_id, f"/competitions/{code}/{resource}", resource_params, report
                    )
                    with session_scope(factory) as session:
                        normalizer(session, payload, _utc(now()).date(), counter)
                        if resource == "scorers":
                            row = session.get(Competition, code)
                            if row is not None and not row.coverage_scorers:
                                row.coverage_scorers = True
                                if code not in inserted_competitions:
                                    counter["updated"] += 1
                except DataNotAvailable as exc:
                    _add_unavailable(report, resource, code, exc)

        _fetch_and_normalize_matches(client, factory, run_id, competitions, report, counter, _utc(now()).date())
        try:
            with session_scope(factory) as session:
                notes = index_corpus(session, settings, embedder=embedder)
            report.notes_index = {
                "files": notes.files,
                "indexed": len(notes.indexed),
                "unchanged": len(notes.unchanged),
                "chunks_written": notes.chunks_written,
            }
        except Exception as exc:
            report.errors.append({"resource": "knowledge-index", "message": _safe_error(exc)})
    except Exception as exc:
        report.errors.append({"resource": "run", "message": _safe_error(exc)})
    report.calls_used = client.stats.calls_used - calls_before
    report.rate_limit_hits = client.stats.rate_limit_hits - rate_limit_hits_before
    report.rows_inserted = counter["inserted"]
    report.rows_updated = counter["updated"]
    report.rows_unchanged = counter["unchanged"]
    report.duration_seconds = max(0.0, (datetime.now(UTC) - started_clock).total_seconds())
    report.status = "failed" if any(error["resource"] == "run" for error in report.errors) else (
        "partial" if report.errors else "succeeded"
    )
    finished = _utc(now())
    with session_scope(factory) as session:
        run = session.get(IngestRun, run_id)
        if run is None:
            raise RuntimeError(f"ingest run {run_id} disappeared before finalization")
        run.finished_at = finished
        run.status = report.status
        run.competitions = report.competitions
        run.calls_used = report.calls_used
        run.rate_limit_hits = report.rate_limit_hits
        run.rows_inserted = report.rows_inserted
        run.rows_updated = report.rows_updated
        run.rows_unchanged = report.rows_unchanged
        run.errors = report.errors
        run.duration_seconds = report.duration_seconds
    return report


def _fetch(
    client: FootballDataClient,
    factory: sessionmaker[Session],
    run_id: str,
    endpoint: str,
    params: Mapping[str, object],
    report: RunReport,
) -> dict[str, Any]:
    payload = client.get_json(endpoint, params)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    with session_scope(factory) as session:
        session.add(
            RawPayload(
                run_id=run_id,
                endpoint=endpoint,
                request_params=dict(params),
                payload=payload,
                content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                fetched_at=datetime.now(UTC),
            )
        )
    return payload


def _fetch_and_normalize_matches(
    client: FootballDataClient,
    factory: sessionmaker[Session],
    run_id: str,
    competitions: list[dict[str, Any]],
    report: RunReport,
    counter: dict[str, int],
    snapshot_date: date,
) -> None:
    starts = [
        parsed
        for competition in competitions
        if (parsed := parse_date((competition.get("currentSeason") or {}).get("startDate"))) is not None
    ]
    if not starts:
        return
    start = min(starts)
    end = snapshot_date + timedelta(days=365)
    codes = sorted(item["code"] for item in competitions if item.get("code"))
    window_start = start
    while window_start <= end:
        window_end = min(window_start + timedelta(days=89), end)
        offset = 0
        page_count = 0
        while True:
            params = {
                "competitions": ",".join(codes),
                "dateFrom": window_start.isoformat(),
                "dateTo": window_end.isoformat(),
                "limit": 500,
                "offset": offset,
            }
            payload = _fetch(client, factory, run_id, "/matches", params, report)
            matches = payload.get("matches")
            if not isinstance(matches, list):
                raise UpstreamError("upstream matches response is missing its list")
            with session_scope(factory) as session:
                for match in matches:
                    upsert_match(session, match, counter)
            page_count += 1
            result_set = payload.get("resultSet") or {}
            total = result_set.get("count")
            offset += len(matches)
            if not matches or len(matches) < 500 or (isinstance(total, int) and offset >= total):
                break
            if page_count >= 100:
                raise UpstreamError(f"upstream pagination did not terminate for {window_start} to {window_end}")
        window_start = window_end + timedelta(days=1)


def _normalize_teams(
    factory: sessionmaker[Session], payload: dict[str, Any], code: str, counter: dict[str, int]
) -> None:
    teams = payload.get("teams")
    if not isinstance(teams, list):
        raise UpstreamError(f"upstream teams response for {code} is missing its list")
    with session_scope(factory) as session:
        for team in teams:
            upsert_team(session, team, code, counter)


def _normalize_team_detail(
    factory: sessionmaker[Session],
    payload: dict[str, Any],
    code: str,
    counter: dict[str, int],
) -> None:
    team = payload.get("team") or payload
    with session_scope(factory) as session:
        upsert_team(session, team, code, counter)


def upsert_competition_row(
    factory: sessionmaker[Session], competition: dict[str, Any], counter: dict[str, int]
) -> bool:
    with session_scope(factory) as session:
        code = competition.get("code")
        inserted = bool(code) and session.get(Competition, code) is None
        upsert_competition(session, competition, counter)
    return inserted


def _season_year(season: dict[str, Any]) -> int | None:
    year = season.get("year")
    if isinstance(year, int):
        return year
    start = parse_date(season.get("startDate"))
    return start.year if start else None


def _add_unavailable(report: RunReport, resource: str, code: str, error: Exception) -> None:
    report.errors.append({"resource": f"{resource}:{code}", "message": _safe_error(error)})


def _safe_error(error: Exception) -> str:
    if isinstance(error, UpstreamError):
        return str(error)
    return f"{type(error).__name__}: {error}"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
