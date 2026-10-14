"""How old the data is, per competition - the endpoint that makes staleness a state, not a guess.

The ledger is the only source. `ingest_runs.competitions` is the *plan* the run was given - the writer
in `ingest/pipeline.py` fills it from the upstream competition list before collecting anything, so a
competition can be listed and still contribute no rows - and `ingest_runs.errors` names what failed
inside it. Both "was this competition in scope" and "how did it go" are answerable without calling
upstream.

Four decisions worth stating, because they were made against real data rather than intuition:

* **A run refreshes only the competitions it lists.** The score-delay measurements also write
  `ingest_runs` rows, with `competitions` NULL, status `succeeded` and one upstream call - nine runs
  of exactly that shape are in the retained volume. Treating a NULL scope as "everything" would
  report all thirteen competitions as fresh after a single one-match poll.
* **A `partial` run still counts as a refresh.** `R-F1.2` makes `partial` the expected outcome when the
  free tier withholds an optional sub-resource: EC has returned 404 for standings every day since
  forever. Calling that stale would mark the whole report stale forever and hide the case the endpoint
  exists to surface, which is data that has genuinely stopped arriving. What failed is visible where it
  belongs - `last_status` and the error list on `/meta/ingest-runs`.
* **A competition with no stored rows is never `fresh`.** Being in the plan is not the same as having
  data: a run can list a competition, collect nothing for it and finish `succeeded`. Marking that
  `fresh` would contradict `/competitions/{code}/standings`, which answers `data_not_available` for the
  same competition - the report would be claiming currency for rows that do not exist. The ledger facts
  are still reported (`last_status`, `last_success_at`, `age_minutes`); only the verdict is withheld.
* **A run stamped in the future does not count.** Clock skew between containers can put `finished_at`
  after the moment of the request; taking it would print a negative age and call data fresh that no
  completed run has refreshed yet. Such a run is ignored, exactly like one that has not finished.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.meta import as_utc
from backend.settings import BackendSettings
from db.models import Competition, IngestRun, Match, Standing, TeamCompetition
from ingest.scheduler import next_run

#: Statuses that mean the competition was refreshed as far as the plan allows.
REFRESHED = ("succeeded", "partial")
#: The statuses a *finished* run can carry. `running` is not one of them, which is why only finished
#: runs are read below: it is also not in the contract's `FreshnessReport.last_status` enum.
FINAL_STATUSES = ("succeeded", "partial", "failed")
#: The table the served standings count refers to.
_TOTAL = or_(Standing.table_type == "TOTAL", Standing.table_type.is_(None))


def freshness_report(session: Session, settings: BackendSettings, *, now: datetime | None = None) -> dict:
    moment = now or datetime.now(UTC)
    competitions = list(session.scalars(select(Competition).order_by(Competition.code)))
    runs = list(session.scalars(select(IngestRun).order_by(IngestRun.started_at.desc(), IngestRun.id.desc())))

    entries = [_entry(session, competition, runs, settings, moment=moment) for competition in competitions]
    ages = [entry["age_minutes"] for entry in entries if entry["age_minutes"] is not None]

    if not entries or all(entry["last_success_at"] is None for entry in entries):
        # No successful ingestion has ever completed for anything we know about.
        overall = "unknown"
    elif any(entry["status"] != "fresh" for entry in entries):
        overall = "stale"
    else:
        overall = "fresh"

    return {
        "as_of": as_utc(moment),
        "overall_status": overall,
        "max_age_minutes": max(ages) if ages else None,
        "next_scheduled_run_at": as_utc(
            next_run(
                moment,
                hour=settings.schedule_hour,
                minute=settings.schedule_minute,
                timezone_name=settings.schedule_timezone,
            )
        ),
        "competitions": entries,
    }


def _entry(
    session: Session,
    competition: Competition,
    runs: list[IngestRun],
    settings: BackendSettings,
    *,
    moment: datetime,
) -> dict:
    scoped = [run for run in runs if competition.code in (run.competitions or [])]
    # Finished, and not stamped in the future: an un-finished run has no outcome to report, and a run
    # finished after the request is a clock that is wrong, not data that is newer.
    finished = [run for run in scoped if _finished_by(run, moment)]
    last = finished[0] if finished else None
    refreshed = next((run for run in finished if run.status in REFRESHED), None)
    last_success = refreshed.finished_at if refreshed else None
    age_minutes = _minutes_between(last_success, moment) if last_success is not None else None
    rows = _row_counts(session, competition.code)
    if age_minutes is None:
        # No run that finished has ever refreshed this competition.
        status = "unknown"
    elif age_minutes > settings.freshness_max_age_minutes:
        status = "stale"
    elif not any(rows.values()):
        # "Listed, collected nothing": a run covered this competition, finished, and stored no rows -
        # so there is nothing to be fresh about. Reporting `fresh` here would contradict
        # `/competitions/{code}/matches`, which answers `data_not_available` for the same code.
        status = "unknown"
    else:
        status = "fresh"

    return {
        "code": competition.code,
        "name": competition.name,
        "last_status": last.status if last is not None else "never",
        "status": status,
        "rows": rows,
        # Both are nullable in the contract, so null is a value a client can act on ("never
        # refreshed") and is always emitted. Only the fields the contract calls non-nullable are
        # pruned when they have nothing to say.
        "last_success_at": as_utc(last_success),
        "age_minutes": age_minutes,
    }


def _row_counts(session: Session, code: str) -> dict:
    """What the API can actually answer for this competition, counted rather than claimed."""
    matches = int(session.scalar(select(func.count()).select_from(Match).where(Match.competition_code == code)) or 0)
    standings = 0
    newest = session.scalar(
        select(func.max(Standing.snapshot_date)).where(Standing.competition_code == code, _TOTAL)
    )
    if newest is not None:
        standings = int(
            session.scalar(
                select(func.count())
                .select_from(Standing)
                .where(Standing.competition_code == code, Standing.snapshot_date == newest, _TOTAL)
            )
            or 0
        )
    teams = int(
        session.scalar(
            select(func.count()).select_from(TeamCompetition).where(TeamCompetition.competition_code == code)
        )
        or 0
    )
    return {"matches": matches, "standings": standings, "teams": teams}


def _finished_by(run: IngestRun, moment: datetime) -> bool:
    """True when the run has an outcome as of `moment`: finished, and not finished in the future."""
    return run.finished_at is not None and _aware(run.finished_at) <= moment


def _aware(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes; everything else in this module is UTC-aware."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def _minutes_between(start: datetime, end: datetime) -> int:
    return int((_aware(end) - _aware(start)).total_seconds() // 60)
