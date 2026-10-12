from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import ingest.__main__ as ingest_cli
from db.models import Competition, IngestRun, Match, Player, RawPayload, Season, Standing, Team, TopScorer
from ingest.client import ClientStats, DataNotAvailable
from ingest.pipeline import run_ingestion


@dataclass
class StubClient:
    calls: int = 0
    unavailable: set[str] | None = None
    match_sent: bool = False

    def __post_init__(self) -> None:
        self.stats = ClientStats()
        self.unavailable = self.unavailable or set()

    def get_json(self, endpoint: str, params: dict | None = None) -> dict:
        self.calls += 1
        self.stats.calls_used += 1
        if endpoint in self.unavailable:
            raise DataNotAvailable(f"upstream resource unavailable: {endpoint}", status_code=403)
        if endpoint == "/competitions":
            self.match_sent = False
            return {
                "competitions": [
                    {
                        "id": 1,
                        "code": "TST",
                        "name": "Test League",
                        "type": "LEAGUE",
                        "area": {"name": "Testland"},
                        "currentSeason": {
                            "year": 2026,
                            "startDate": "2026-10-10",
                            "endDate": "2027-06-30",
                        },
                    }
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
                    }
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


def test_score_delay_poll_persists_responses_and_run_ledger(settings, engine, monkeypatch) -> None:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    class PollingClient:
        def __init__(self, **_kwargs) -> None:
            self.stats = ClientStats()
            self.responses = iter(
                [
                    {"match": {"status": "FINISHED", "score": {"fullTime": {"home": None, "away": None}}}},
                    {"match": {"status": "FINISHED", "score": {"fullTime": {"home": 2, "away": 1}}}},
                ]
            )

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return None

        def get_json(self, _endpoint: str) -> dict:
            self.stats.calls_used += 1
            return next(self.responses)

    monkeypatch.setattr(ingest_cli, "FootballDataClient", PollingClient)
    monkeypatch.setattr(ingest_cli.time, "sleep", lambda _seconds: None)

    result = ingest_cli.measure_score_delay(settings, factory, 1234, poll_seconds=1, timeout_seconds=10)

    assert result["match_id"] == 1234
    assert result["home_score"] == 2
    assert result["away_score"] == 1
    with factory() as session:
        run = session.scalar(select(IngestRun).where(IngestRun.calls_used == 2))
        assert run is not None
        assert run.status == "succeeded"
        assert session.scalar(select(func.count()).select_from(RawPayload).where(RawPayload.run_id == run.id)) == 2
