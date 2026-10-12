"""M2 ingestion persistence checks against the real Compose Postgres and embedding model."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from db.models import Competition, IngestRun, Match, Player, RawPayload, Standing, Team, TopScorer
from db.session import create_db_engine
from db.settings import Settings
from ingest.client import ClientStats, ResourceNotFound
from ingest.knowledge.embedding import OllamaEmbedder
from ingest.pipeline import run_ingestion

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def stack_settings() -> Settings:
    settings = Settings.from_env()
    assert settings.is_postgres, "integration tests require the Compose Postgres DATABASE_URL"
    return settings


@pytest.fixture(scope="module")
def stack_engine(stack_settings: Settings):
    engine = create_db_engine(stack_settings)
    yield engine
    engine.dispose()


FIXTURE_IDS = range(987654300, 987654400)


@pytest.fixture(autouse=True)
def remove_fixture_rows(stack_engine):
    """Keep the synthetic competition out of the retained database once a test is done."""
    yield
    factory = sessionmaker(bind=stack_engine, expire_on_commit=False, future=True)
    with factory.begin() as session:
        for model in (TopScorer, Standing, Match):
            session.execute(delete(model).where(model.competition_code == "M2T"))
        session.execute(delete(Player).where(Player.id.in_(FIXTURE_IDS)))
        session.execute(delete(Team).where(Team.id.in_(FIXTURE_IDS)))
        session.execute(delete(Competition).where(Competition.code == "M2T"))
        for run in session.scalars(select(IngestRun)):
            if run.competitions == ["M2T"]:
                session.delete(run)


class FixtureClient:
    def __init__(self, not_found: frozenset[str] = frozenset()) -> None:
        self.stats = ClientStats()
        self.match_sent = False
        self.not_found = not_found

    def get_json(self, endpoint: str, _params: dict | None = None) -> dict:
        self.stats.calls_used += 1
        if endpoint in self.not_found:
            raise ResourceNotFound(f"upstream resource not found: {endpoint}", status_code=404)
        if endpoint == "/competitions":
            self.match_sent = False
            return {
                "competitions": [
                    {
                        "code": "M2T",
                        "name": "M2 test competition",
                        "type": "LEAGUE",
                        "currentSeason": {
                            "year": datetime.now(UTC).year,
                            "startDate": datetime.now(UTC).date().isoformat(),
                        },
                    }
                ]
            }
        if endpoint.endswith("/teams"):
            return {
                "teams": [
                    {
                        "id": 987654321,
                        "name": "M2 Test FC",
                        "squad": [
                            {"id": 987654322, "name": "M2 Test Player", "position": "Forward"}
                        ],
                    }
                ]
            }
        if endpoint.endswith("/standings"):
            return {
                "competition": {"code": "M2T"},
                "season": {"year": datetime.now(UTC).year},
                "standings": [
                    {
                        "type": "TOTAL",
                        "table": [
                            {
                                "position": 1,
                                "team": {"id": 987654321, "name": "M2 Test FC"},
                                "playedGames": 0,
                                "points": 0,
                            }
                        ],
                    }
                ],
            }
        if endpoint.endswith("/scorers"):
            return {
                "competition": {"code": "M2T"},
                "season": {"year": datetime.now(UTC).year},
                "scorers": [
                    {
                        "player": {"id": 987654322, "name": "M2 Test Player", "position": "Forward"},
                        "team": {"id": 987654321, "name": "M2 Test FC"},
                        "playedMatches": 0,
                        "goals": 0,
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
                        "id": 987654324,
                        "competition": {"code": "M2T"},
                        "season": {"year": datetime.now(UTC).year},
                        "status": "FINISHED",
                        "utcDate": datetime.now(UTC).isoformat(),
                        "homeTeam": {"id": 987654321, "name": "M2 Test FC"},
                        "awayTeam": {"id": 987654323, "name": "M2 Visitor FC"},
                        "score": {"fullTime": {"home": 1, "away": 0}},
                    }
                ],
            }
        raise AssertionError(f"unexpected fixture endpoint: {endpoint}")


@pytest.fixture
def stack_embedder(stack_settings: Settings):
    with OllamaEmbedder(
        host=stack_settings.ollama_host,
        model=stack_settings.embedding_model,
        dim=stack_settings.embedding_dim,
    ) as embedder:
        yield embedder


def test_ingestion_writes_idempotent_rows_and_bronze_payloads(stack_settings: Settings, stack_engine, stack_embedder):
    factory = sessionmaker(bind=stack_engine, expire_on_commit=False, future=True)
    client = FixtureClient()
    run_time = datetime.now(UTC)

    def now() -> datetime:
        return run_time

    first = run_ingestion(stack_settings, factory, client, stack_embedder, now=now)
    second = run_ingestion(stack_settings, factory, client, stack_embedder, now=now)

    assert first.status == "succeeded"
    assert first.rows_inserted > 0
    assert second.status == "succeeded"
    assert second.rows_inserted == 0
    assert second.rows_unchanged > 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Competition).where(Competition.code == "M2T")) == 1
        assert session.scalar(select(func.count()).select_from(Team).where(Team.id == 987654321)) == 1
        match = session.get(Match, 987654324)
        assert match is not None
        assert (match.score_full_time_home, match.score_full_time_away) == (1, 0)
        assert (
            session.scalar(
                select(func.count())
                .select_from(Standing)
                .where(Standing.competition_code == "M2T", Standing.snapshot_date == run_time.date())
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(TopScorer)
                .where(TopScorer.competition_code == "M2T", TopScorer.snapshot_date == run_time.date())
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(RawPayload)
                .where(RawPayload.run_id.in_([first.run_id, second.run_id]))
            )
            == first.calls_used + second.calls_used
        )
        assert session.scalar(select(func.count()).select_from(IngestRun).where(IngestRun.status == "succeeded")) >= 2


def test_missing_optional_resource_leaves_a_partial_run_with_matches(
    stack_settings: Settings, stack_engine, stack_embedder
):
    factory = sessionmaker(bind=stack_engine, expire_on_commit=False, future=True)
    client = FixtureClient(not_found=frozenset({"/competitions/M2T/standings"}))

    report = run_ingestion(stack_settings, factory, client, stack_embedder)

    assert report.status == "partial"
    assert [error["resource"] for error in report.errors] == ["standings:M2T"]
    with factory() as session:
        assert session.get(Match, 987654324) is not None
        run = session.get(IngestRun, report.run_id)
        assert run is not None and run.status == "partial"
