"""`/meta/freshness`: what "how old is this" means, and the four decisions behind it.

Rule 2 says freshness is part of every answer, so the endpoint that states it has to be right in the
cases that are easy to get wrong:

* a run that lists no competitions (the score-delay poll) refreshes nothing;
* a `partial` run did refresh what it could reach - treating it as failure would mark the whole report
  stale forever, because EC's missing standings are permanent;
* a *failed* run does not make the data older than it is;
* a competition nobody has ever collected is `unknown`, not `stale`, and not `fresh`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.services.freshness import freshness_report
from backend.settings import BackendSettings
from db.models import IngestRun, new_id
from tests import api_helpers


def report(session: Session, settings: BackendSettings, *, now: datetime) -> dict:
    """The report as of a chosen moment, never the wall clock: an age assertion that could drift with
    the machine's clock is an assertion that will fail on somebody else's machine."""
    return freshness_report(session, settings, now=now)


def entry(body: dict, code: str) -> dict:
    return next(row for row in body["competitions"] if row["code"] == code)


@pytest.fixture
def scoped(session: Session, seeded, backend_settings: BackendSettings) -> dict:
    """The seeded world, read as of the moment its runs were written against."""
    return report(session, backend_settings, now=seeded.now)


def stamp(seeded, **offset) -> str:
    """The ISO stamp `seeded.now - offset` would be served as."""
    from backend.meta import as_utc

    return as_utc(seeded.now - timedelta(**offset))


def test_a_partial_run_still_counts_as_a_refresh(scoped) -> None:
    """PL's newest scoped run is `partial` because EC's standings 404. PL's own tables were written."""
    premier = entry(scoped, "PL")
    assert premier["last_status"] == "partial"
    assert premier["status"] == "fresh"


def test_the_newest_scoped_run_sets_the_status_but_not_the_age(scoped, seeded) -> None:
    """BL1's newest scoped run failed; the successful one an hour earlier is what the age comes from.
    A failed refresh makes the data no older than it was."""
    bundesliga = entry(scoped, "BL1")
    assert bundesliga["last_status"] == "failed"
    assert bundesliga["status"] == "fresh"
    assert bundesliga["last_success_at"] == stamp(seeded, hours=2, minutes=50), "the successful run, not the failure"


def test_a_run_with_no_competition_scope_refreshes_nothing(scoped, seeded) -> None:
    """The score-delay poll writes `status: succeeded`, one call, `competitions: NULL`. If that counted
    as a refresh, every competition would look fresh after a single match poll - which is exactly the
    failure mode this endpoint exists to catch."""
    assert entry(scoped, "WC")["last_status"] == "never"
    assert entry(scoped, "WC")["status"] == "unknown"
    assert entry(scoped, "WC")["last_success_at"] is None
    assert entry(scoped, "WC")["age_minutes"] is None
    # SA is refreshed only by its own 60-day-old run, not by the recent measurement.
    assert entry(scoped, "SA")["last_success_at"] == stamp(seeded, days=60, minutes=-10)
    assert entry(scoped, "SA")["status"] == "stale"


def test_the_report_aggregates_the_worst_case(scoped, seeded) -> None:
    from backend.settings import DEFAULT_FRESHNESS_MAX_AGE_MINUTES

    assert scoped["overall_status"] == "stale", "one stale competition makes the report stale"
    assert scoped["max_age_minutes"] == max(
        row["age_minutes"] for row in scoped["competitions"] if row["age_minutes"] is not None
    )
    assert scoped["max_age_minutes"] > DEFAULT_FRESHNESS_MAX_AGE_MINUTES
    assert scoped["as_of"] == stamp(seeded)


def test_the_threshold_is_inclusive_and_configurable(session, seeded, settings) -> None:
    """Exactly at the limit is fresh; a minute over is stale. The limit is a setting, because the
    daily schedule and the free tier's delay are deployment facts, not constants."""
    at_limit = BackendSettings(db=settings, freshness_max_age_minutes=85)
    just_over = BackendSettings(db=settings, freshness_max_age_minutes=84)
    assert entry(report(session, at_limit, now=seeded.now), "PL")["status"] == "fresh"
    assert entry(report(session, just_over, now=seeded.now), "PL")["status"] == "stale"


def test_the_next_scheduled_run_is_reported_in_utc(session, seeded, settings) -> None:
    """The schedule is configured in local time and reported in UTC, because a client should not have
    to know the deployment's timezone to read a timestamp."""
    configured = BackendSettings(
        db=settings, schedule_hour=7, schedule_minute=30, schedule_timezone="Europe/Berlin"
    )
    body = report(session, configured, now=seeded.now)
    when = datetime.fromisoformat(body["next_scheduled_run_at"].replace("Z", "+00:00"))
    # 07:30 in Berlin is 05:30 UTC in October (CEST, +02:00), on the next local day.
    assert body["next_scheduled_run_at"].endswith("Z")
    assert (when.hour, when.minute) == (5, 30)
    assert when > seeded.now, "a scheduled run in the past is not the next one"
    assert when - seeded.now < timedelta(days=1)


def test_row_counts_report_what_can_actually_be_answered(scoped) -> None:
    """`rows` is what turns "fresh" into something checkable: fresh means the run happened, and the
    counts say whether it brought anything."""
    premier = entry(scoped, "PL")["rows"]
    assert premier == {"matches": 6, "standings": 3, "teams": 3}, "6 matches in all, the newest TOTAL table, 3 teams"
    assert entry(scoped, "WC")["rows"] == {"matches": 0, "standings": 0, "teams": 0}
    assert entry(scoped, "CL")["rows"]["standings"] == 2


def test_a_competition_that_has_never_succeeded_is_unknown_not_stale(session, settings) -> None:
    """An empty deployment must say "unknown", not "stale": nothing is late if nothing was promised."""
    body = freshness_report(session, BackendSettings(db=settings), now=datetime(2026, 10, 14, 12, 0, tzinfo=UTC))
    assert body["overall_status"] == "unknown"
    assert body["max_age_minutes"] is None
    assert body["competitions"] == []


def test_a_competition_nobody_collected_keeps_the_report_from_claiming_fresh(session, seeded, settings) -> None:
    """The contract: "fresh when every competition is within its expected refresh window, stale when
    any is not, unknown when no successful run has ever completed". A competition we cannot vouch for
    is not within its window, so the overall status is not `fresh` - the per-competition row says
    which one and why. Never claim freshness the ledger does not support.
    """
    session.query(IngestRun).filter(IngestRun.id == seeded.runs["old"]).delete()
    session.commit()
    body = freshness_report(session, BackendSettings(db=settings), now=seeded.now)
    assert entry(body, "SA")["status"] == "unknown"
    assert entry(body, "WC")["status"] == "unknown"
    assert body["overall_status"] == "stale"
    assert entry(body, "PL")["status"] == "fresh", "and the ones that are fine still say so"


def test_all_fresh_when_every_competition_was_refreshed_in_time(session, seeded, settings) -> None:
    # A run that reached everything, a few minutes ago: the state a healthy daily schedule leaves.
    session.add(
        IngestRun(
            id=new_id(),
            started_at=seeded.now - timedelta(minutes=40),
            finished_at=seeded.now - timedelta(minutes=35),
            status="succeeded",
            trigger="schedule",
            competitions=[
                api_helpers.COMPETITION,
                api_helpers.OTHER_COMPETITION,
                api_helpers.GROUP_COMPETITION,
                api_helpers.STALE_COMPETITION,
                api_helpers.NEVER_INGESTED,
            ],
            errors=[],
        )
    )
    session.commit()
    body = freshness_report(session, BackendSettings(db=settings, freshness_max_age_minutes=26 * 60), now=seeded.now)
    fresh = {row["code"] for row in body["competitions"] if row["status"] == "fresh"}
    assert fresh == {
        api_helpers.COMPETITION,
        api_helpers.OTHER_COMPETITION,
        api_helpers.GROUP_COMPETITION,
    }
    # ...except the two with nothing stored. The run covered them, so `last_status` and the age are
    # honest, but a competition with no rows is not fresh, and the aggregate cannot claim fresh either.
    for code in (api_helpers.NEVER_INGESTED, api_helpers.STALE_COMPETITION):
        empty = entry(body, code)
        assert empty["last_status"] == "succeeded", code
        assert empty["age_minutes"] == 35, code
        assert not any(empty["rows"].values()), code
        assert empty["status"] == "unknown", code
    assert body["overall_status"] == "stale"
    assert body["max_age_minutes"] <= 26 * 60


def test_freshness_never_calls_upstream(session, seeded, backend_settings) -> None:
    """The report is a computation over the ledger. If it needed a network call it could not run
    inside a request at all (`AGENTS.md` rule 3)."""
    body = report(session, backend_settings, now=seeded.now)
    assert "competitions" in body and "as_of" in body
    assert all("rows" in row for row in body["competitions"])


def test_the_http_response_is_a_report_not_an_envelope(client, auth, seeded) -> None:
    """The contract gives `FreshnessReport` its own `as_of` field instead of the usual `meta` block."""
    body = client.get("/meta/freshness", headers=auth).json()
    assert set(body) == {"as_of", "overall_status", "max_age_minutes", "next_scheduled_run_at", "competitions"}
    assert all("request_id" not in row for row in body["competitions"])
    assert body["as_of"].endswith("Z"), "RFC 3339 in UTC, parseable by any client"


def test_freshness_lists_every_competition_the_catalog_knows(client, auth, seeded) -> None:
    """A competition missing from the report would be a competition nobody can tell is stale."""
    body = client.get("/meta/freshness", headers=auth).json()
    codes = [row["code"] for row in body["competitions"]]
    assert codes == ["BL1", "CL", "PL", "SA", "WC"]
    assert all(row["name"] for row in body["competitions"])


def test_a_run_that_covered_a_competition_but_collected_nothing_is_not_fresh(session, seeded, settings) -> None:
    """The plan is not the data. `ingest/pipeline.py` writes `competitions` from the upstream
    competition list *before* collecting, so a run can list a code, finish `succeeded` and store no
    rows for it. The report must not call that fresh while `/competitions/{code}/matches` answers
    `data_not_available` - an adversarial review found exactly this contradiction."""
    session.add(
        IngestRun(
            id=new_id(),
            started_at=seeded.now - timedelta(minutes=12),
            finished_at=seeded.now - timedelta(minutes=8),
            status="succeeded",
            trigger="schedule",
            competitions=[api_helpers.NEVER_INGESTED],
            errors=[],
        )
    )
    session.commit()
    body = report(session, BackendSettings(db=settings, freshness_max_age_minutes=26 * 60), now=seeded.now)
    world_cup = entry(body, api_helpers.NEVER_INGESTED)
    assert world_cup["age_minutes"] == 8, "the ledger fact is still reported"
    assert world_cup["last_status"] == "succeeded"
    assert world_cup["rows"] == {"matches": 0, "standings": 0, "teams": 0}
    assert world_cup["status"] == "unknown", "nothing is stored, so there is nothing to be fresh"


def test_a_run_stamped_in_the_future_refreshes_nothing(session, seeded, settings) -> None:
    """Clock skew between containers can date a run after the request. Reading it would print a
    negative age and call data fresh that no completed run has refreshed yet."""
    session.add(
        IngestRun(
            id=new_id(),
            started_at=seeded.now + timedelta(hours=6),
            finished_at=seeded.now + timedelta(hours=6),
            status="succeeded",
            trigger="schedule",
            competitions=[api_helpers.STALE_COMPETITION],
            errors=[],
        )
    )
    session.commit()
    body = report(session, BackendSettings(db=settings, freshness_max_age_minutes=26 * 60), now=seeded.now)
    south_africa = entry(body, api_helpers.STALE_COMPETITION)
    assert south_africa["last_success_at"] == stamp(seeded, days=60, minutes=-10), "the older real run wins"
    assert south_africa["age_minutes"] > 0
    assert south_africa["status"] == "stale"


def test_an_unfinished_run_is_not_reported_as_a_status_or_an_age(session, seeded, settings) -> None:
    """`running` is not in the contract's `last_status` enum, and a run with no `finished_at` has no
    outcome to report. Only finished runs are read, so the field can never carry a status the contract
    does not list - the review filed this as a latent hole."""
    session.add(
        IngestRun(
            id=new_id(),
            started_at=seeded.now - timedelta(minutes=3),
            finished_at=None,
            status="running",
            trigger="schedule",
            competitions=[api_helpers.COMPETITION],
            errors=[],
        )
    )
    session.commit()
    body = report(session, BackendSettings(db=settings, freshness_max_age_minutes=26 * 60), now=seeded.now)
    premier = entry(body, api_helpers.COMPETITION)
    assert premier["last_status"] == "partial", "the newest *finished* run, not the one in flight"
    assert "running" not in {row["last_status"] for row in body["competitions"]}