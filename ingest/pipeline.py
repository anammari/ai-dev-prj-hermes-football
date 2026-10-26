"""Daily collection from football-data.org into bronze and normalized serving tables."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from db.models import Competition, IngestRun, RawPayload, new_id
from db.session import session_scope
from db.settings import Settings
from ingest.client import DataNotAvailable, FootballDataClient, ResourceNotFound, UpstreamError
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
from telemetry import get_tracer
from telemetry import metrics as telemetry_metrics

logger = logging.getLogger(__name__)

tracer = get_tracer("hermes.ingest")

# Bronze payloads older than this are pruned at the end of each run; None keeps them forever.
DEFAULT_RAW_RETENTION_DAYS = 30
# Upstream rejects /matches ranges longer than 10 days with HTTP 400.
MATCH_WINDOW_DAYS = 10

# Optional sub-resources the free plan may withhold (403) or not publish at all (404).
_UNAVAILABLE = (DataNotAvailable, ResourceNotFound)


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
    payloads_unchanged: int = 0
    payloads_pruned: int = 0
    matches_skipped: int = 0
    notes_index: dict[str, Any] = field(default_factory=dict)


def run_ingestion(
    settings: Settings,
    factory: sessionmaker[Session],
    client: FootballDataClient,
    embedder: Embedder,
    *,
    trigger: str = "manual",
    raw_retention_days: int | None = DEFAULT_RAW_RETENTION_DAYS,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RunReport:
    """One run, with a span and three counters. The wrapper keeps the pipeline itself unchanged."""
    with tracer.start_as_current_span("ingest.run", record_exception=False) as span:
        report = _run_ingestion(
            settings,
            factory,
            client,
            embedder,
            trigger=trigger,
            raw_retention_days=raw_retention_days,
            now=now,
        )
        span.set_attribute("status", report.status)
        span.set_attribute("competitions", len(report.competitions))
        span.set_attribute("calls_used", report.calls_used)
        span.set_attribute("rate_limit_hits", report.rate_limit_hits)
        span.set_attribute("errors", len(report.errors))
        telemetry_metrics.INGEST_RUNS.add(1, {"status": report.status})
        telemetry_metrics.INGEST_DURATION.record(report.duration_seconds, {"status": report.status})
        telemetry_metrics.INGEST_CALLS.add(report.calls_used, {"trigger": trigger})
        return report


def _run_ingestion(
    settings: Settings,
    factory: sessionmaker[Session],
    client: FootballDataClient,
    embedder: Embedder,
    *,
    trigger: str = "manual",
    raw_retention_days: int | None = DEFAULT_RAW_RETENTION_DAYS,
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

        for position, competition in enumerate(snapshots, start=1):
            code = competition["code"]
            logger.info("ingesting competition %s (%d/%d)", code, position, len(snapshots))
            try:
                _collect_competition(
                    client,
                    factory,
                    run_id,
                    competition,
                    report,
                    counter,
                    inserted_competitions,
                    team_details_seen,
                    _utc(now()).date(),
                )
            except (UpstreamError, ValueError) as exc:
                # One competition degrading, or publishing a record the normalizer rejects, must not
                # stop the others. Only these two are caught: a database fault still aborts the run,
                # because that is a problem on our side rather than bad provider data.
                _add_unavailable(report, "competition", code, exc)
                logger.warning("competition %s skipped: %s", code, exc)

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
    # Retention runs even when collection failed. A run that dies early has still written bronze, and
    # if cleanup only happened on the happy path then a stretch of failed days would let old payloads
    # outlive the window. A cleanup failure is reported as `partial` rather than `failed`: the day's
    # data did land, only the housekeeping did not.
    if raw_retention_days is not None:
        try:
            report.payloads_pruned = prune_raw_payloads(
                factory, retention_days=raw_retention_days, keep_run_id=run_id, now=_utc(now())
            )
        except Exception as exc:
            report.errors.append({"resource": "prune", "message": _safe_error(exc)})
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


def _collect_competition(
    client: FootballDataClient,
    factory: sessionmaker[Session],
    run_id: str,
    competition: dict[str, Any],
    report: RunReport,
    counter: dict[str, int],
    inserted_competitions: set[str | None],
    team_details_seen: set[int],
    snapshot_date: date,
) -> None:
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
            except _UNAVAILABLE as exc:
                _add_unavailable(report, "squad", str(team_id), exc)
    except _UNAVAILABLE as exc:
        _add_unavailable(report, "teams", code, exc)

    for resource, column, normalizer in (
        ("standings", "coverage_standings", upsert_standings),
        ("scorers", "coverage_scorers", upsert_scorers),
    ):
        try:
            resource_params = {**params, **({"limit": 500} if resource == "scorers" else {})}
            payload = _fetch(client, factory, run_id, f"/competitions/{code}/{resource}", resource_params, report)
            with session_scope(factory) as session:
                normalizer(session, payload, snapshot_date, counter)
                _set_coverage(session, code, column, True, inserted_competitions=inserted_competitions, counter=counter)
        except _UNAVAILABLE as exc:
            # A 403 or 404 is the provider saying it will not serve this table. Record that in the
            # flag as well as the run log, or the API presents an unavailable table as an empty one
            # that still looks valid. Flipping it back on success covers access returning later.
            _add_unavailable(report, resource, code, exc)
            with session_scope(factory) as session:
                _set_coverage(
                    session, code, column, False, inserted_competitions=inserted_competitions, counter=counter
                )


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
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    with session_scope(factory) as session:
        # The hash is a change-detection fingerprint: a payload byte-identical to an earlier one
        # means the upstream resource did not change between runs.
        seen_before = session.scalar(
            select(RawPayload.id)
            .where(RawPayload.endpoint == endpoint, RawPayload.content_hash == content_hash)
            .limit(1)
        )
        if seen_before is not None:
            report.payloads_unchanged += 1
        session.add(
            RawPayload(
                run_id=run_id,
                endpoint=endpoint,
                request_params=dict(params),
                payload=payload,
                content_hash=content_hash,
                fetched_at=datetime.now(UTC),
            )
        )
    return payload


def close_orphaned_runs(
    factory: sessionmaker[Session],
    *,
    now: datetime | None = None,
    max_age_hours: int = 3,
) -> list[str]:
    """Close `running` rows that no process owns any more.

    A container killed mid-run leaves a row that says `running` forever. The freshness report ignores
    it (it has no outcome), but the on-call alert correctly reads it as a stuck run and would fire
    every day for a crash that happened once. Startup is the right place to decide it is dead: this
    process is the only writer of the ledger, so a row older than the threshold cannot be alive.
    """
    moment = _utc(now or datetime.now(UTC))
    closed: list[str] = []
    with session_scope(factory) as session:
        for run in session.scalars(select(IngestRun).where(IngestRun.status == "running")):
            started = _utc(run.started_at)
            if moment - started < timedelta(hours=max_age_hours):
                continue
            run.finished_at = moment
            run.status = "failed"
            run.duration_seconds = max(0.0, (moment - started).total_seconds())
            run.errors = list(run.errors or []) + [
                {"resource": "recovery", "message": "orphaned running row closed at startup"}
            ]
            closed.append(run.id)
    return closed


def prune_raw_payloads(
    factory: sessionmaker[Session], *, retention_days: int, keep_run_id: str, now: datetime
) -> int:
    """Delete bronze payloads older than the retention window; the current run is never pruned."""
    if retention_days < 1:
        raise ValueError("raw payload retention must be at least one day")
    cutoff = now - timedelta(days=retention_days)
    with session_scope(factory) as session:
        result = session.execute(
            delete(RawPayload).where(RawPayload.fetched_at < cutoff, RawPayload.run_id != keep_run_id)
        )
        return int(result.rowcount or 0)


def _has_both_teams(match: dict[str, Any]) -> bool:
    # Future knockout fixtures are published before their teams are decided.
    return all((match.get(side) or {}).get("id") is not None for side in ("homeTeam", "awayTeam"))


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
        window_end = min(window_start + timedelta(days=MATCH_WINDOW_DAYS - 1), end)
        try:
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
                        if not _has_both_teams(match):
                            report.matches_skipped += 1
                            continue
                        upsert_match(session, match, counter)
                page_count += 1
                result_set = payload.get("resultSet") or {}
                total = result_set.get("count")
                offset += len(matches)
                if not matches or len(matches) < 500 or (isinstance(total, int) and offset >= total):
                    break
                if page_count >= 100:
                    raise UpstreamError(f"upstream pagination did not terminate for {window_start} to {window_end}")
        except (UpstreamError, ValueError) as exc:
            # Same rule as the competition loop: one malformed fixture skips its window, and a
            # database fault is not swallowed here either.
            report.errors.append(
                {"resource": f"matches:{window_start}..{window_end}", "message": _safe_error(exc)}
            )
            logger.warning("matches window %s..%s skipped: %s", window_start, window_end, exc)
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


def _set_coverage(
    session: Session,
    code: str,
    column: str,
    value: bool,
    *,
    inserted_competitions: set[str | None],
    counter: dict[str, int],
) -> None:
    """Record whether the provider served an optional sub-resource for this competition."""
    row = session.get(Competition, code)
    if row is None or getattr(row, column) == value:
        return
    setattr(row, column, value)
    if code not in inserted_competitions:
        counter["updated"] += 1


def _add_unavailable(report: RunReport, resource: str, code: str, error: Exception) -> None:
    report.errors.append({"resource": f"{resource}:{code}", "message": _safe_error(error)})


def _safe_error(error: Exception) -> str:
    if isinstance(error, UpstreamError):
        return str(error)
    return f"{type(error).__name__}: {error}"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
