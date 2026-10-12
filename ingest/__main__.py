"""Run or schedule the M2 ingestion pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
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
    delay = commands.add_parser("measure-score-delay", help="poll a finished match until its score is published")
    delay.add_argument("--match-id", type=int, help="provider match id (defaults to latest finished scoreless match)")
    delay.add_argument("--poll-seconds", type=int, default=60)
    delay.add_argument("--timeout-seconds", type=int, default=86400)
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
            )
    finally:
        engine.dispose()


def measure_score_delay(
    settings: Settings,
    factory: sessionmaker[Session],
    match_id: int | None,
    *,
    poll_seconds: int,
    timeout_seconds: int,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if poll_seconds <= 0 or timeout_seconds <= 0:
        raise ValueError("poll and timeout values must be positive")
    if match_id is None:
        with session_scope(factory) as session:
            match_id = session.scalar(
                select(Match.id)
                .where(
                    Match.status == "FINISHED",
                    (Match.score_full_time_home.is_(None) | Match.score_full_time_away.is_(None)),
                )
                .order_by(Match.utc_date.desc())
                .limit(1)
            )
        if match_id is None:
            raise RuntimeError("no finished match with an unpublished full-time score is available to poll")
    started = datetime.now(UTC)
    run_id = new_id()
    with session_scope(factory) as session:
        session.add(IngestRun(id=run_id, started_at=started, status="running", trigger="manual"))
    first_finished_without_score: datetime | None = None
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
                fetched_at = datetime.now(UTC)
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
                score = ((match.get("score") or {}).get("fullTime") or {})
                home, away = score.get("home"), score.get("away")
                if match.get("status") == "FINISHED" and first_finished_without_score is None:
                    if home is None or away is None:
                        first_finished_without_score = fetched_at
                if home is not None and away is not None and match.get("status") == "FINISHED":
                    if first_finished_without_score is None:
                        raise RuntimeError(
                            f"match {match_id} already had its full-time score on the first finished poll"
                        )
                    observed_at = datetime.now(UTC)
                    result = {
                        "match_id": match_id,
                        "home_score": home,
                        "away_score": away,
                        "finished_without_score_observed_at": first_finished_without_score.isoformat(),
                        "score_observed_at": observed_at.isoformat(),
                        "delay_seconds": round((observed_at - first_finished_without_score).total_seconds(), 3),
                        "calls_used": client.stats.calls_used,
                    }
                    _finish_measurement(factory, run_id, client.stats.calls_used, client.stats.rate_limit_hits)
                    print(json.dumps(result, sort_keys=True))
                    return result
                remaining = deadline - datetime.now(UTC).timestamp()
                if remaining <= 0:
                    raise TimeoutError(
                        f"match {match_id} full-time score was not published within {timeout_seconds} seconds"
                    )
                sleep(min(poll_seconds, remaining))
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
