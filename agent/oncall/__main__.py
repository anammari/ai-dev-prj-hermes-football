"""The on-call process: a health endpoint, a check loop, a daily digest and three CLI modes.

The loop is one coroutine doing a 60 s tick. On each tick it evaluates the alert, updates the two
observable gauges, writes `alerts.json`, and - once a day at `ONCALL_DIGEST_HOUR` - writes the digest.
No database writes, no model, no upstream: `agent_readonly` would refuse a write even if this code
tried.

The CLI is how the alert is demonstrated without waiting a day:

    python -m agent.oncall --once              # evaluate against the real ledger
    python -m agent.oncall --simulate stale    # a synthetic observation, no database
    python -m agent.oncall --digest            # write today's digest now
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from agent.oncall import alerts
from agent.oncall.config import OnCallSettings
from agent.oncall.digest import write as write_digest
from agent.oncall.notify import send as send_alert
from agent.oncall.queries import Snapshot, collect, engine_for
from telemetry import configure as configure_telemetry
from telemetry import metrics as telemetry_metrics
from telemetry import shutdown as shutdown_telemetry

LOGGER = logging.getLogger("hermes.oncall")


class Runner:
    def __init__(self, settings: OnCallSettings, *, engine=None) -> None:
        self.settings = settings
        self.engine = engine
        self.state: alerts.AlertState | None = None
        self.last_check: datetime | None = None
        self.last_digest: str | None = None
        self.last_error: str | None = None
        self._load_previous()

    @property
    def report_dir(self) -> Path:
        return self.settings.report_dir

    def _state_path(self) -> Path:
        return self.report_dir / "alerts.json"

    def _load_previous(self) -> None:
        path = self._state_path()
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.state = alerts.AlertState(
                name=payload.get("name") or alerts.ALERT_NAME,
                state=payload.get("state") or alerts.STATE_OK,
                since=datetime.fromisoformat(payload["since"]),
                reason=payload.get("reason"),
                observed_minutes=payload.get("observed_minutes"),
                consecutive_failures=int(payload.get("consecutive_failures") or 0),
                breaches=int(payload.get("breaches") or 0),
            )
        except (OSError, ValueError, KeyError, TypeError):
            LOGGER.warning("alert state could not be read; starting from a clean state")

    def _write_state(self, state: alerts.AlertState) -> None:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        payload = asdict(state)
        payload["since"] = state.since.isoformat()
        self._state_path().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def check(self, *, now: datetime | None = None) -> Snapshot | None:
        moment = now or datetime.now(UTC)
        if self.settings.db_dsn is None:
            self.last_error = "ONCALL_DB_DSN is unset"
            LOGGER.warning("oncall check skipped: %s", self.last_error)
            return None
        if self.engine is None:
            self.engine = engine_for(self.settings.db_dsn)
        snapshot = collect(self.engine, now=moment, stale_minutes=self.settings.stale_minutes)
        policy = alerts.AlertPolicy(
            stale_minutes=self.settings.stale_minutes,
            consecutive_failures=self.settings.consecutive_failures,
            required_breaches=self.settings.required_breaches,
            running_stale_hours=self.settings.running_stale_hours,
        )
        state, transition = alerts.evaluate(snapshot.observation, policy, self.state)
        self.state = state
        self.last_check = moment
        for entry in snapshot.freshness.get("competitions") or []:
            if entry.get("age_minutes") is not None:
                telemetry_metrics.set_freshness_age(str(entry.get("code")), float(entry["age_minutes"]))
        telemetry_metrics.set_alert_firing(state.name, state.firing)
        telemetry_metrics.ONCALL_CHECKS.add(1, {"state": state.state})
        self._write_state(state)
        if transition:
            LOGGER.warning(
                "alert.transition alert=%s state=%s reason=%s age_minutes=%s failures=%s",
                state.name,
                state.state,
                state.reason,
                state.observed_minutes,
                state.consecutive_failures,
            )
            try:
                send_alert(state, snapshot.observation, self.settings)
            except Exception:  # noqa: BLE001 - a notification must not stop the loop
                LOGGER.exception("alert notification raised")
        self.last_error = None
        return snapshot

    def maybe_digest(self, *, now: datetime | None = None) -> Path | None:
        moment = now or datetime.now(UTC)
        local = moment.astimezone(ZoneInfo(self.settings.timezone))
        today = local.date().isoformat()
        if local.hour < self.settings.digest_hour or self.last_digest == today:
            return None
        snapshot = self.check(now=moment)
        if snapshot is None or self.state is None:
            return None
        path = write_digest(snapshot, self.state, report_dir=self.report_dir, generated_at=moment)
        self.last_digest = today
        telemetry_metrics.ONCALL_DIGESTS.add(1, {"status": "written"})
        LOGGER.info("digest written: %s", path)
        return path

    def digest_now(self, *, now: datetime | None = None) -> Path | None:
        moment = now or datetime.now(UTC)
        snapshot = self.check(now=moment)
        if snapshot is None or self.state is None:
            return None
        return write_digest(snapshot, self.state, report_dir=self.report_dir, generated_at=moment)


def _simulated(kind: str, settings: OnCallSettings, now: datetime) -> alerts.Observation:
    if kind == "stale":
        return alerts.Observation(
            now=now,
            last_success_at=now - timedelta(minutes=settings.stale_minutes + 60),
            recent_statuses=("succeeded",),
            oldest_running_at=None,
        )
    if kind == "failures":
        return alerts.Observation(
            now=now,
            last_success_at=now - timedelta(minutes=30),
            recent_statuses=("failed", "failed", "succeeded"),
            oldest_running_at=None,
        )
    if kind == "stuck":
        return alerts.Observation(
            now=now,
            last_success_at=now - timedelta(minutes=30),
            recent_statuses=("succeeded",),
            oldest_running_at=now - timedelta(hours=settings.running_stale_hours + 1),
        )
    return alerts.Observation(
        now=now,
        last_success_at=now - timedelta(minutes=30),
        recent_statuses=("succeeded",),
        oldest_running_at=None,
    )


def create_app(settings: OnCallSettings, runner: Runner | None = None) -> FastAPI:
    configure_telemetry("hermes-oncall")
    runner = runner or Runner(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async def loop() -> None:
            while True:
                try:
                    await asyncio.to_thread(runner.check)
                    await asyncio.to_thread(runner.maybe_digest)
                except Exception:  # noqa: BLE001 - the loop keeps going; the error is in the health body
                    LOGGER.exception("oncall check failed")
                    runner.last_error = "check_failed"
                await asyncio.sleep(max(5, settings.check_seconds))

        task = asyncio.create_task(loop())
        try:
            yield
        finally:
            task.cancel()
            if runner.engine is not None:
                runner.engine.dispose()
            shutdown_telemetry()

    app = FastAPI(
        title="Hermes Football on-call",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict:
        state = runner.state
        return {
            "status": "ok",
            "service": "hermes-oncall",
            "db": "configured" if settings.db_dsn else "disabled",
            "alert": state.state if state else "unknown",
            "alert_reason": state.reason if state else None,
            "last_check": runner.last_check.isoformat() if runner.last_check else None,
            "last_digest": runner.last_digest,
            "telegram": "configured" if settings.telegram_ready else "disabled",
            "error": runner.last_error,
        }

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m agent.oncall")
    parser.add_argument("--once", action="store_true", help="evaluate once against the real ledger")
    parser.add_argument("--digest", action="store_true", help="write today's digest now")
    parser.add_argument(
        "--simulate",
        choices=["stale", "failures", "stuck", "ok"],
        help="evaluate a synthetic observation; no database and no notification",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    configure_telemetry("hermes-oncall")
    settings = OnCallSettings.from_env()
    now = datetime.now(UTC)

    if args.simulate:
        observation = _simulated(args.simulate, settings, now)
        policy = alerts.AlertPolicy(
            stale_minutes=settings.stale_minutes,
            consecutive_failures=settings.consecutive_failures,
            required_breaches=settings.required_breaches,
            running_stale_hours=settings.running_stale_hours,
        )
        state, _ = alerts.evaluate(observation, policy, None)
        state, transition = alerts.evaluate(observation, policy, state)
        telemetry_metrics.set_alert_firing(state.name, state.firing)
        print(json.dumps({**asdict(state), "since": state.since.isoformat(), "transition": transition}, indent=2))
        print(alerts.message(state, observation))
        shutdown_telemetry()
        return

    runner = Runner(settings)
    if args.once or args.digest:
        snapshot = runner.check(now=now)
        if snapshot is None:
            print(json.dumps({"error": runner.last_error}))
            shutdown_telemetry()
            sys.exit(1)
        if args.digest:
            path = write_digest(snapshot, runner.state, report_dir=runner.report_dir, generated_at=now)  # type: ignore[arg-type]
            print(json.dumps({"digest": str(path), "alert": asdict(runner.state) if runner.state else None}, indent=2))
        else:
            print(
                json.dumps(
                    {
                        "alert": asdict(runner.state) if runner.state else None,
                        "last_success_at": snapshot.observation.last_success_at.isoformat()
                        if snapshot.observation.last_success_at
                        else None,
                        "recent_statuses": list(snapshot.observation.recent_statuses),
                        "eval_age_days": snapshot.eval_age_days,
                    },
                    indent=2,
                    default=str,
                )
            )
        if runner.engine is not None:
            runner.engine.dispose()
        shutdown_telemetry()
        return

    import uvicorn

    uvicorn.run(
        create_app(settings, runner),
        host="0.0.0.0",  # noqa: S104 - container-internal only; no published port
        port=settings.health_port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
