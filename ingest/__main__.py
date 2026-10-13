"""Run or schedule the M2 ingestion pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import statistics
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from db.models import IngestRun, Match, RawPayload, new_id
from db.session import create_db_engine, create_session_factory, session_scope
from db.settings import Settings
from ingest.client import FootballDataClient
from ingest.knowledge.embedding import OllamaEmbedder
from ingest.pipeline import DEFAULT_RAW_RETENTION_DAYS, _safe_error, run_ingestion
from ingest.scheduler import run_daily


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m ingest")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="run ingestion once")
    commands.add_parser("schedule", help="run ingestion daily at INGEST_SCHEDULE_HOUR")
    delay = commands.add_parser(
        "measure-score-delay",
        help="poll a live or recent match and report how old the provider's data is",
    )
    delay.add_argument("--match-id", type=int, help="provider match id (defaults to the most recent match)")
    delay.add_argument("--poll-seconds", type=int, default=60)
    delay.add_argument("--timeout-seconds", type=int, default=7200, help="stop after this long and report")
    delay.add_argument("--recent-hours", type=int, default=6, help="how far back the default match may have kicked off")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)

    raw_retention_days = int(os.environ.get("RAW_PAYLOAD_RETENTION_DAYS", DEFAULT_RAW_RETENTION_DAYS))

    def action(trigger: str = "manual") -> dict[str, Any]:
        with FootballDataClient(
            base_url=settings.upstream_base_url,
            api_key=settings.upstream_api_key,
        ) as client, OllamaEmbedder(
            host=settings.ollama_host,
            model=settings.embedding_model,
            dim=settings.embedding_dim,
        ) as embedder:
            report = run_ingestion(
                settings,
                factory,
                client,
                embedder,
                trigger=trigger,
                raw_retention_days=raw_retention_days,
            )
        return asdict(report)

    try:
        if args.command == "run":
            print(json.dumps(action(), sort_keys=True))
        elif args.command == "schedule":
            # Fail at startup, not at the first scheduled run, when the token is missing or a placeholder.
            FootballDataClient(base_url=settings.upstream_base_url, api_key=settings.upstream_api_key).close()
            run_daily(
                lambda: print(json.dumps(action("schedule"), sort_keys=True), flush=True),
                hour=int(os.environ.get("INGEST_SCHEDULE_HOUR", "2")),
                minute=int(os.environ.get("INGEST_SCHEDULE_MINUTE", "0")),
                timezone_name=os.environ.get("INGEST_TIMEZONE", "UTC"),
            )
        else:
            measure_score_delay(
                settings,
                factory,
                args.match_id,
                poll_seconds=args.poll_seconds,
                timeout_seconds=args.timeout_seconds,
                recent_hours=args.recent_hours,
            )
    finally:
        engine.dispose()


def _utc_now() -> datetime:
    return datetime.now(UTC)


class NoRecentMatch(RuntimeError):
    """No match kicked off recently enough to measure."""


def measure_score_delay(
    settings: Settings,
    factory: sessionmaker[Session],
    match_id: int | None,
    *,
    poll_seconds: int,
    timeout_seconds: int,
    recent_hours: int = 6,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = _utc_now,
) -> dict[str, Any]:
    """Measure how old the provider's match data is at the moment we observe it.

    The first version of this command waited for a *finished* match to publish its full-time
    score. That premise is false, and a live run proved it: the provider publishes the score
    while the match is still `IN_PLAY`, so a finished-but-scoreless match never occurs and the
    command could only ever raise. What is real — and what the freshness claim in
    `hermes/agent-knowledge/policy/free-tier-delay-and-coverage.md` rests on — is the gap
    between the provider's own `lastUpdated` stamp and the moment we fetch the match. This
    measures that gap on every poll, and records the status at which the score first appears.

    Running out of time before full time measures a match that is still in play; it is not a
    failure, so the run still ends in a report.
    """
    if poll_seconds <= 0 or timeout_seconds <= 0:
        raise ValueError("poll and timeout values must be positive")
    if recent_hours <= 0:
        raise ValueError("recent_hours must be positive")

    started = now()
    if match_id is None:
        cutoff = started - timedelta(hours=recent_hours)
        with session_scope(factory) as session:
            match_id = session.scalar(
                select(Match.id)
                # Fixtures scheduled for later seasons also fall inside the look-back window, and they
                # sort as the most recent, so the upper bound is what keeps this to matches that have
                # actually kicked off.
                .where(Match.utc_date >= cutoff, Match.utc_date <= started)
                .order_by(Match.utc_date.desc())
                .limit(1)
            )
        if match_id is None:
            raise NoRecentMatch(
                f"no match kicked off in the last {recent_hours}h to poll; run this during a live match "
                "or pass MATCH_ID=<id>"
            )

    run_id = new_id()
    with session_scope(factory) as session:
        session.add(IngestRun(id=run_id, started_at=started, status="running", trigger="manual"))
    observations: list[dict[str, Any]] = []
    client: FootballDataClient | None = None
    try:
        client = FootballDataClient(
            base_url=settings.upstream_base_url,
            api_key=settings.upstream_api_key,
        )
        with client:
            deadline = started.timestamp() + timeout_seconds
            while True:
                payload = client.get_json(f"/matches/{match_id}")
                fetched_at = now()
                canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                with session_scope(factory) as session:
                    session.add(
                        RawPayload(
                            run_id=run_id,
                            endpoint=f"/matches/{match_id}",
                            request_params={},
                            payload=payload,
                            content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                            fetched_at=fetched_at,
                        )
                    )
                match = payload.get("match") or payload
                status = match.get("status")
                score = (match.get("score") or {}).get("fullTime") or {}
                home, away = score.get("home"), score.get("away")
                has_score = home is not None and away is not None
                last_updated = _parse_last_updated(match.get("lastUpdated"))
                observations.append(
                    {
                        "fetched_at": fetched_at,
                        "status": status,
                        "has_score": has_score,
                        "lag_seconds": (fetched_at - last_updated).total_seconds() if last_updated else None,
                    }
                )
                if status == "FINISHED" and has_score:
                    break
                remaining = deadline - now().timestamp()
                if remaining <= 0:
                    break
                sleep(min(poll_seconds, remaining))

            result = _summarise_measurement(match_id, observations, client.stats)
            _finish_measurement(factory, run_id, client.stats.calls_used, client.stats.rate_limit_hits)
            print(json.dumps(result, sort_keys=True))
            return result
    except Exception as exc:
        _finish_measurement(
            factory,
            run_id,
            client.stats.calls_used if client is not None else 0,
            client.stats.rate_limit_hits if client is not None else 0,
            status="failed",
            errors=[{"resource": "score-delay-measurement", "message": _safe_error(exc)}],
        )
        raise


def _parse_last_updated(value: Any) -> datetime | None:
    """Parse the provider's `lastUpdated` stamp, tolerating a missing or malformed value."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


# Past this, a `FINISHED` match is a closed record that has stopped being updated, so its
# `lastUpdated` gap measures the age of that record rather than any score delay.
_STALE_RECORD_SECONDS = 600


def _summarise_measurement(
    match_id: int,
    observations: list[dict[str, Any]],
    stats: Any,
) -> dict[str, Any]:
    """Turn the poll history into the numbers the data-freshness claim is made of."""
    lags = [row["lag_seconds"] for row in observations if row["lag_seconds"] is not None]
    first_scored = next((row for row in observations if row["has_score"]), None)
    finished_scored = next((row for row in observations if row["status"] == "FINISHED" and row["has_score"]), None)
    finished_lag = finished_scored["lag_seconds"] if finished_scored else None
    note = None
    if finished_lag is not None and finished_lag > _STALE_RECORD_SECONDS:
        note = (
            "this match stopped being updated long ago, so the lag above is the age of a closed record "
            "rather than a score delay; poll a live match for the number the freshness note quotes"
        )
    return {
        "match_id": match_id,
        "polls": len(observations),
        "statuses_seen": dict(sorted(Counter(str(row["status"]) for row in observations).items())),
        "score_first_seen_status": first_scored["status"] if first_scored else None,
        "score_first_seen_at": first_scored["fetched_at"].isoformat() if first_scored else None,
        "score_published_before_full_time": bool(first_scored and first_scored["status"] != "FINISHED"),
        "finished_observed_at": finished_scored["fetched_at"].isoformat() if finished_scored else None,
        "finished_lag_seconds": _round_or_none(finished_lag),
        "lag_seconds": {
            "min": _round_or_none(min(lags) if lags else None),
            "median": _round_or_none(statistics.median(lags) if lags else None),
            "max": _round_or_none(max(lags) if lags else None),
        },
        "note": note,
        "calls_used": stats.calls_used,
        "rate_limit_hits": stats.rate_limit_hits,
    }


def _finish_measurement(
    factory: sessionmaker[Session],
    run_id: str,
    calls_used: int,
    rate_limit_hits: int,
    *,
    status: str = "succeeded",
    errors: list[dict[str, str]] | None = None,
) -> None:
    finished = datetime.now(UTC)
    with session_scope(factory) as session:
        run = session.get(IngestRun, run_id)
        if run is None:
            raise RuntimeError(f"score-delay measurement {run_id} disappeared before finalization")
        run.finished_at = finished
        run.status = status
        run.calls_used = calls_used
        run.rate_limit_hits = rate_limit_hits
        run.rows_inserted = 0
        run.rows_updated = 0
        run.rows_unchanged = 0
        run.errors = errors or []
        started = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=UTC)
        run.duration_seconds = max(0.0, (finished - started).total_seconds())


if __name__ == "__main__":
    main()
