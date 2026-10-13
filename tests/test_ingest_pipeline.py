from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import ingest.__main__ as ingest_cli
from db.models import Competition, IngestRun, Match, Player, RawPayload, Season, Standing, Team, TopScorer
from ingest.client import ClientStats, DataNotAvailable, ResourceNotFound, UpstreamError
from ingest.pipeline import run_ingestion


@dataclass
class StubClient:
    calls: int = 0
    unavailable: set[str] | None = None
    not_found: set[str] | None = None
    broken: set[str] | None = None
    second_competition: bool = False
    match_sent: bool = False

    def __post_init__(self) -> None:
        self.stats = ClientStats()
        self.unavailable = self.unavailable or set()
        self.not_found = self.not_found or set()
        self.broken = self.broken or set()
        self.requested: list[str] = []

    def get_json(self, endpoint: str, params: dict | None = None) -> dict:
        self.calls += 1
        self.stats.calls_used += 1
        self.requested.append(endpoint)
        if endpoint == "/matches" and params:
            span = (date.fromisoformat(params["dateTo"]) - date.fromisoformat(params["dateFrom"])).days + 1
            if span > 10:
                raise UpstreamError("upstream returned HTTP 400 for /matches", status_code=400)
        if endpoint in self.unavailable:
            raise DataNotAvailable(f"upstream resource unavailable: {endpoint}", status_code=403)
        if endpoint in self.not_found:
            raise ResourceNotFound(f"upstream resource not found: {endpoint}", status_code=404)
        if endpoint in self.broken:
            raise UpstreamError(f"upstream returned HTTP 500 for {endpoint}", status_code=500)
        if endpoint == "/competitions":
            self.match_sent = False
            codes = ["TST", "TS2"] if self.second_competition else ["TST"]
            return {
                "competitions": [
                    {
                        "id": index,
                        "code": code,
                        "name": f"Test League {code}",
                        "type": "LEAGUE",
                        "area": {"name": "Testland"},
                        "currentSeason": {
                            "year": 2026,
                            "startDate": "2026-10-10",
                            "endDate": "2027-06-30",
                        },
                    }
                    for index, code in enumerate(codes, start=1)
                ]
            }
        if endpoint.endswith("/teams"):
            team = self._team()
            team.pop("squad")
            return {"teams": [team]}
        if endpoint.startswith("/teams/"):
            return {"team": self._team(with_squad=True)}
        if endpoint.endswith("/standings"):
            return {
                "competition": {"code": "TST"},
                "season": {"year": 2026},
                "standings": [
                    {
                        "type": "TOTAL",
                        "stage": "REGULAR_SEASON",
                        "table": [
                            {
                                "position": 1,
                                "team": self._team(),
                                "playedGames": 0,
                                "won": 0,
                                "draw": 0,
                                "lost": 0,
                                "points": 0,
                            }
                        ],
                    }
                ],
            }
        if endpoint.endswith("/scorers"):
            return {
                "competition": {"code": "TST"},
                "season": {"year": 2026},
                "scorers": [
                    {
                        "player": {
                            "id": 20,
                            "name": "Test Player",
                            "position": "Forward",
                            "nationality": "Testland",
                        },
                        "team": self._team(),
                        "playedMatches": 1,
                        "goals": 1,
                        "assists": 0,
                        "penalties": 0,
                    }
                ],
            }
        if endpoint == "/matches":
            if self.match_sent:
                return {"resultSet": {"count": 1}, "matches": []}
            self.match_sent = True
            return {
                "resultSet": {"count": 1},
                "matches": [
                    {
                        "id": 30,
                        "competition": {"code": "TST"},
                        "season": {"year": 2026},
                        "status": "FINISHED",
                        "utcDate": "2026-10-10T12:00:00Z",
                        "homeTeam": self._team(),
                        "awayTeam": {"id": 11, "name": "Visitor FC"},
                        "score": {
                            "winner": "HOME_TEAM",
                            "duration": "REGULAR",
                            "fullTime": {"home": 2, "away": 1},
                            "halfTime": {"home": 1, "away": 0},
                        },
                    },
                    {
                        "id": 31,
                        "competition": {"code": "TST"},
                        "season": {"year": 2026},
                        "status": "TIMED",
                        "utcDate": "2027-05-01T12:00:00Z",
                        "homeTeam": {"id": None, "name": None},
                        "awayTeam": {"id": None, "name": None},
                        "score": {"fullTime": {"home": None, "away": None}},
                    },
                ],
            }
        raise AssertionError(f"unexpected endpoint: {endpoint} {params}")

    @staticmethod
    def _team(*, with_squad: bool = False) -> dict:
        return {
            "id": 10,
            "name": "Test FC",
            "area": {"name": "Testland"},
            "squad": [
                {"id": 20, "name": "Test Player", "position": "Forward", "nationality": "Testland"}
            ] if with_squad else [],
        }


def test_run_is_idempotent_and_persists_bronze_and_serving_rows(settings, engine, embedder) -> None:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    client = StubClient()

    def now() -> datetime:
        return datetime(2026, 10, 10, tzinfo=UTC)

    first = run_ingestion(settings, factory, client, embedder, now=now)
    second = run_ingestion(settings, factory, client, embedder, now=now)

    assert first.status == "succeeded"
    assert first.rows_inserted > 0
    assert first.matches_skipped == 1
    assert second.status == "succeeded"
    assert second.rows_inserted == 0
    assert second.rows_unchanged > 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Competition)) == 1
        assert session.scalar(select(func.count()).select_from(Season)) == 1
        assert session.scalar(select(func.count()).select_from(Team)) == 2
        assert session.scalar(select(func.count()).select_from(Player)) == 1
        assert session.scalar(select(func.count()).select_from(Standing)) == 1
        assert session.scalar(select(func.count()).select_from(TopScorer)) == 1
        match = session.get(Match, 30)
        assert match is not None
        assert (match.score_full_time_home, match.score_full_time_away) == (2, 1)
        assert session.scalar(select(func.count()).select_from(RawPayload)) == client.calls
        runs = list(session.scalars(select(IngestRun).order_by(IngestRun.started_at)))
        assert [run.status for run in runs] == ["succeeded", "succeeded"]
        assert all(run.calls_used > 0 for run in runs)


def test_forbidden_competition_resource_is_recorded_as_partial(settings, engine, embedder) -> None:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    client = StubClient(unavailable={"/competitions/TST/standings"})

    def now() -> datetime:
        return datetime(2026, 10, 10, tzinfo=UTC)

    report = run_ingestion(settings, factory, client, embedder, now=now)
    assert report.status == "partial"
    assert any(item["resource"] == "standings:TST" for item in report.errors)
    assert report.rows_inserted > 0


def test_missing_standings_is_partial_and_other_competitions_still_load(settings, engine, embedder) -> None:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    client = StubClient(not_found={"/competitions/TST/standings"}, second_competition=True)

    report = run_ingestion(settings, factory, client, embedder, now=_fixed_now)

    assert report.status == "partial"
    assert [error["resource"] for error in report.errors] == ["standings:TST"]
    assert "/competitions/TS2/standings" in client.requested
    assert "/matches" in client.requested
    assert report.rows_inserted > 0


def test_upstream_error_in_one_competition_does_not_abort_the_run(settings, engine, embedder) -> None:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    client = StubClient(broken={"/competitions/TST/scorers"}, second_competition=True)

    report = run_ingestion(settings, factory, client, embedder, now=_fixed_now)

    assert report.status == "partial"
    assert [error["resource"] for error in report.errors] == ["competition:TST"]
    assert "/competitions/TS2/scorers" in client.requested
    assert "/matches" in client.requested
    with factory() as session:
        run = session.get(IngestRun, report.run_id)
        assert run is not None and run.status == "partial"


def test_catalog_failure_fails_the_run(settings, engine, embedder) -> None:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    client = StubClient(broken={"/competitions"})

    report = run_ingestion(settings, factory, client, embedder, now=_fixed_now)

    assert report.status == "failed"
    assert [error["resource"] for error in report.errors] == ["run"]
    assert client.requested == ["/competitions"]


def test_bronze_payloads_are_pruned_after_retention_and_repeats_are_flagged(settings, engine, embedder) -> None:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    client = StubClient()

    first = run_ingestion(settings, factory, client, embedder, now=_fixed_now)
    second = run_ingestion(settings, factory, client, embedder, now=_fixed_now)
    assert first.payloads_unchanged < first.calls_used
    assert second.payloads_unchanged == second.calls_used

    later = run_ingestion(
        settings, factory, client, embedder, raw_retention_days=1, now=lambda: _fixed_now() + timedelta(days=30)
    )
    assert later.payloads_pruned == first.calls_used + second.calls_used
    with factory() as session:
        remaining = session.scalars(select(RawPayload.run_id)).all()
        assert set(remaining) == {later.run_id}


def _fixed_now() -> datetime:
    return datetime(2026, 10, 10, tzinfo=UTC)


def _iso_z(moment: datetime) -> str:
    """Render a moment the way the upstream `lastUpdated` field renders it."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_score_delay_measures_the_last_updated_gap(settings, engine, monkeypatch) -> None:
    """The provider publishes the score while the match is still in play, so there is no
    scoreless-finished window to wait for. The command measures the gap between the provider's
    own `lastUpdated` stamp and the fetch, and records the status the score first appeared in."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    t0 = datetime(2026, 10, 12, 23, 40, tzinfo=UTC)
    clock = {"now": t0}
    # (status, the lag the provider shows, home, away) — each poll happens 60s after the last.
    script = [("TIMED", 120, None, None), ("IN_PLAY", 90, 1, 0), ("FINISHED", 60, 2, 1)]
    payloads = [
        {
            "status": status,
            "lastUpdated": _iso_z(t0 + timedelta(seconds=60 * index) - timedelta(seconds=lag)),
            "score": {"fullTime": {"home": home, "away": away}},
        }
        for index, (status, lag, home, away) in enumerate(script)
    ]

    class PollingClient:
        def __init__(self, **_kwargs) -> None:
            self.stats = ClientStats()
            self.responses = iter(payloads)

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return None

        def get_json(self, _endpoint: str) -> dict:
            self.stats.calls_used += 1
            return next(self.responses)

    monkeypatch.setattr(ingest_cli, "FootballDataClient", PollingClient)

    result = ingest_cli.measure_score_delay(
        settings,
        factory,
        1234,
        poll_seconds=60,
        timeout_seconds=600,
        sleep=lambda seconds: clock.__setitem__("now", clock["now"] + timedelta(seconds=seconds)),
        now=lambda: clock["now"],
    )

    assert result["match_id"] == 1234
    assert result["polls"] == 3
    assert result["statuses_seen"] == {"FINISHED": 1, "IN_PLAY": 1, "TIMED": 1}
    assert result["score_first_seen_status"] == "IN_PLAY"
    assert result["score_published_before_full_time"] is True
    assert result["finished_lag_seconds"] == 60.0
    assert result["lag_seconds"] == {"min": 60.0, "median": 90.0, "max": 120.0}
    assert result["note"] is None
    with factory() as session:
        run = session.scalar(select(IngestRun).where(IngestRun.calls_used == 3))
        assert run is not None
        assert run.status == "succeeded"
        assert session.scalar(select(func.count()).select_from(RawPayload).where(RawPayload.run_id == run.id)) == 3


def test_score_delay_reports_a_match_still_in_play_rather_than_failing(settings, engine, monkeypatch) -> None:
    """Running out of time before full time measures a match still being played, not a failure."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    clock = {"now": datetime(2026, 10, 12, 23, 40, tzinfo=UTC)}

    class PollingClient:
        def __init__(self, **_kwargs) -> None:
            self.stats = ClientStats()

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return None

        def get_json(self, _endpoint: str) -> dict:
            self.stats.calls_used += 1
            return {
                "status": "IN_PLAY",
                "lastUpdated": _iso_z(clock["now"] - timedelta(seconds=75)),
                "score": {"fullTime": {"home": 1, "away": 0}},
            }

    monkeypatch.setattr(ingest_cli, "FootballDataClient", PollingClient)

    result = ingest_cli.measure_score_delay(
        settings,
        factory,
        1234,
        poll_seconds=60,
        timeout_seconds=180,
        sleep=lambda seconds: clock.__setitem__("now", clock["now"] + timedelta(seconds=seconds)),
        now=lambda: clock["now"],
    )

    assert result["polls"] == 4
    assert result["finished_observed_at"] is None
    assert result["finished_lag_seconds"] is None
    assert result["score_published_before_full_time"] is True
    assert result["lag_seconds"]["median"] == 75.0
    with factory() as session:
        run = session.scalar(select(IngestRun).where(IngestRun.calls_used == 4))
        assert run is not None
        assert run.status == "succeeded"


def test_score_delay_without_a_recent_match_explains_itself(settings, engine, monkeypatch) -> None:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    class NeverCalled:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("the upstream must not be called when there is nothing to poll")

    monkeypatch.setattr(ingest_cli, "FootballDataClient", NeverCalled)

    with pytest.raises(ingest_cli.NoRecentMatch, match="no match kicked off"):
        ingest_cli.measure_score_delay(
            settings,
            factory,
            None,
            poll_seconds=60,
            timeout_seconds=60,
            now=lambda: datetime(2030, 1, 1, tzinfo=UTC),
            sleep=lambda _seconds: None,
        )


def test_score_delay_flags_a_closed_record_instead_of_quoting_it(settings, engine, monkeypatch) -> None:
    """A match that finished hours ago has stopped being updated, so its `lastUpdated` gap is the
    age of a closed record. The report must say so rather than let it read as a score delay."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    now = datetime(2026, 10, 12, 23, 40, tzinfo=UTC)

    class PollingClient:
        def __init__(self, **_kwargs) -> None:
            self.stats = ClientStats()

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return None

        def get_json(self, _endpoint: str) -> dict:
            self.stats.calls_used += 1
            return {
                "status": "FINISHED",
                "lastUpdated": _iso_z(now - timedelta(hours=6)),
                "score": {"fullTime": {"home": 2, "away": 1}},
            }

    monkeypatch.setattr(ingest_cli, "FootballDataClient", PollingClient)

    result = ingest_cli.measure_score_delay(
        settings,
        factory,
        555033,
        poll_seconds=60,
        timeout_seconds=600,
        sleep=lambda _seconds: None,
        now=lambda: now,
    )

    assert result["polls"] == 1
    assert result["finished_lag_seconds"] == 21600.0
    assert result["note"] is not None
    assert "closed record" in result["note"]


def test_score_delay_default_picks_a_match_that_has_kicked_off(settings, engine, monkeypatch) -> None:
    """Fixtures scheduled for a later season also fall inside the look-back window and sort as the
    most recent, so the default must exclude anything that has not kicked off yet."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    now = datetime(2026, 10, 13, 2, 0, tzinfo=UTC)
    with factory() as session:
        session.add(Competition(code="PL", name="Premier League"))
        session.add_all([Team(id=57, name="Arsenal FC"), Team(id=61, name="Chelsea FC")])
        session.flush()
        session.add_all(
            [
                Match(
                    id=9001,
                    competition_code="PL",
                    status="FINISHED",
                    utc_date=now - timedelta(hours=3),
                    home_team_id=57,
                    away_team_id=61,
                ),
                Match(
                    id=9002,
                    competition_code="PL",
                    status="TIMED",
                    utc_date=now + timedelta(days=200),
                    home_team_id=57,
                    away_team_id=61,
                ),
            ]
        )
        session.commit()

    polled: list[str] = []

    class RecordingClient:
        def __init__(self, **_kwargs) -> None:
            self.stats = ClientStats()

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return None

        def get_json(self, endpoint: str) -> dict:
            self.stats.calls_used += 1
            polled.append(endpoint)
            return {
                "status": "FINISHED",
                "lastUpdated": _iso_z(now - timedelta(hours=3)),
                "score": {"fullTime": {"home": 1, "away": 0}},
            }

    monkeypatch.setattr(ingest_cli, "FootballDataClient", RecordingClient)

    result = ingest_cli.measure_score_delay(
        settings,
        factory,
        None,
        poll_seconds=60,
        timeout_seconds=600,
        now=lambda: now,
        sleep=lambda _seconds: None,
    )

    assert result["match_id"] == 9001
    assert polled == ["/matches/9001"]
