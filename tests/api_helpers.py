"""Shared machinery for the API tests: the contract made executable, and a seeded database.

Two jobs live here.

**The contract as a checker.** `json_schema()` turns an OpenAPI 3.0 schema into the JSON Schema that
means the same thing, and `validate()` runs a response body through it. That is what makes
`tests/test_api_contract.py` a drift test rather than a shape-by-shape wish list: it does not name the
fields it expects, it reads them from `openapi.yaml` and fails when what the API sent disagrees. The
conversion is small on purpose (`nullable` -> `anyOf` with null, `$ref` resolved, prose keys dropped)
and the test suite checks that it *can* fail, because a validator that accepts everything is
decoration.

**A seed built from the contract's own examples.** `request_for()` builds a concrete request for an
operation out of the examples the contract publishes (match 419823, team 57, season 2026, ...), and
`seed_api()` puts exactly those rows in the database. So the contract's examples are run against a
database that matches them, and a documented example that stops making sense shows up as a failing
test rather than a stale comment.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy.orm import Session

from db.models import (
    AgentTurn,
    Competition,
    IngestRun,
    KnowledgeChunk,
    Match,
    Player,
    Standing,
    Team,
    TeamCompetition,
    TopScorer,
    new_id,
)
from db.settings import REPO_ROOT
from ingest.knowledge.embedding import Embedder

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

#: The reviewed contract, at the path `backend/settings.py` serves it from.
CONTRACT_PATH = REPO_ROOT / "openapi.yaml"
CONTRACT: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
SCHEMAS: dict[str, Any] = CONTRACT["components"]["schemas"]
PARAMETER_COMPONENTS: dict[str, Any] = CONTRACT["components"].get("parameters", {})

# --- The ids the contract's examples use, and the seed provides ---------------------------------
COMPETITION = "PL"  # CompetitionCode's first member
OTHER_COMPETITION = "BL1"
GROUP_COMPETITION = "CL"
STALE_COMPETITION = "SA"
NEVER_INGESTED = "WC"
SEASON = 2026
MATCH_ID = 419823
TEAM = 57
OPPONENT = 61
THIRD = 63


# ---------------------------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------------------------


def operations() -> dict[str, tuple[str, str, dict[str, Any]]]:
    """operationId -> (METHOD, path, operation object), for every operation in the contract."""
    found: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for path, item in CONTRACT["paths"].items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                found[operation["operationId"]] = (method.upper(), path, operation)
    return found


def operation(operation_id: str) -> tuple[str, str, dict[str, Any]]:
    return operations()[operation_id]


def resolve(node: dict[str, Any]) -> dict[str, Any]:
    """Follow a `$ref`, which is all this contract uses."""
    if "$ref" in node:
        return SCHEMAS[node["$ref"].rsplit("/", 1)[-1]]
    return node


def parameter(entry: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in entry:
        return PARAMETER_COMPONENTS[entry["$ref"].rsplit("/", 1)[-1]]
    return entry


def parameters(operation_id: str) -> list[dict[str, Any]]:
    return [parameter(entry) for entry in operation(operation_id)[2].get("parameters", [])]


def parameter_schema(operation_id: str, name: str) -> dict[str, Any]:
    """The contract's schema for one parameter, with `$ref`s resolved."""
    for entry in parameters(operation_id):
        if entry["name"] == name:
            return resolve(entry.get("schema") or {})
    raise KeyError(f"{operation_id} has no parameter {name}")


def response_schema(operation_id: str, status: str = "200") -> dict[str, Any] | None:
    responses = operation(operation_id)[2]["responses"]
    if status not in responses:
        return None
    return (responses[status].get("content") or {}).get("application/json", {}).get("schema")


#: The validation keywords this translator carries over unchanged. Every keyword that constrains a
#: value has to be here or the sweep would pass a response the contract forbids: `minItems` was
#: missing once, and the contract's "exactly two teams" went unchecked. `test_every_validation
#: _keyword_in_the_contract_is_translated` walks the whole contract and fails on anything new.
CARRIED_KEYWORDS = (
    "type",
    "enum",
    "required",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "minProperties",
    "maxProperties",
    "format",
    "pattern",
    "additionalProperties",
    "uniqueItems",
    "multipleOf",
)

#: Structural keywords, translated rather than copied. Also the ones the walker below allows through.
STRUCTURAL_KEYWORDS = ("allOf", "oneOf", "anyOf", "items", "properties")

#: Prose and presentation, deliberately dropped: they say nothing about whether a value is legal.
IGNORED_KEYWORDS = ("description", "title", "example", "examples", "default", "deprecated", "discriminator")


def json_schema(node: dict[str, Any]) -> dict[str, Any]:
    """An OpenAPI 3.0 schema, as the JSON Schema that means the same thing.

    Only what this contract uses is translated, and prose is dropped:
    `$ref` is resolved, `nullable: true` becomes `anyOf: [..., {"type": "null"}]` (the 3.0 reading,
    which is why a null passes a field the contract marked nullable and fails one it did not),
    `allOf`/`oneOf`/`anyOf` recurse, and `example`/`description`/`discriminator` are ignored.
    """
    node = resolve(node)
    if node.get("nullable"):
        inner = json_schema({key: value for key, value in node.items() if key != "nullable"})
        return {"anyOf": [inner, {"type": "null"}]}

    translated: dict[str, Any] = {}
    for keyword in ("allOf", "oneOf", "anyOf"):
        if keyword in node:
            translated[keyword] = [json_schema(part) for part in node[keyword]]
    for keyword in CARRIED_KEYWORDS:
        if keyword in node:
            translated[keyword] = node[keyword]
    if "items" in node:
        translated["items"] = json_schema(node["items"])
    if "properties" in node:
        translated["properties"] = {name: json_schema(value) for name, value in node["properties"].items()}
    return translated


def collapsed(node: dict[str, Any]) -> dict[str, Any]:
    """A parameter schema with the null branch of `anyOf` removed.

    FastAPI writes `int | None` as `anyOf: [{type: integer}, {type: null}]`, and the same concept in
    the contract is `type: integer, nullable: true`. Comparing the two needs one of them flattened,
    and flattening on the generated side keeps the contract's wording as the thing asserted.
    """
    branches = node.get("anyOf")
    if isinstance(branches, list):
        remaining = [branch for branch in branches if branch.get("type") != "null"]
        if len(remaining) == 1:
            return {**collapsed(remaining[0]), **{k: v for k, v in node.items() if k != "anyOf"}}
    return node


def validate(body: Any, node: dict[str, Any], *, where: str) -> None:
    """Fail with every disagreement, not the first, so one run fixes one shape."""
    validator = Draft202012Validator(json_schema(node), format_checker=FormatChecker())
    problems = sorted(validator.iter_errors(body), key=lambda error: list(error.absolute_path))
    if problems:
        lines = [
            f"  {where}: /{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
            for error in problems[:12]
        ]
        raise AssertionError(f"{where} does not validate against the contract:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------------------------
# Building a request out of the contract's own examples
# ---------------------------------------------------------------------------------------------


def _value(schema: dict[str, Any]) -> Any:
    """The example the contract gives, its default, or something of the right type."""
    if "example" in schema:
        return schema["example"]
    if schema.get("enum"):
        return schema["enum"][0]
    if schema.get("format") == "uuid":
        return str(uuid.uuid4())
    if schema.get("default") is not None:
        return schema["default"]
    return {"integer": 1, "number": 0.5, "boolean": True}.get(schema.get("type"), "x")


class _Omit:
    """Passed as an override to leave a parameter out even though the contract gives it an example."""

    def __repr__(self) -> str:
        return "OMIT"


OMIT = _Omit()


#: Parameters the sweep drops or pins, with the reason. Everything not listed here is filled from the
#: contract's own example, so the set should stay tiny. Shared by the unit sweep and the stack sweep.
SWEEP_OVERRIDES: dict[str, dict[str, Any]] = {
    # The documented window (2026-10-10..2026-10-12) predates every fixture, and a `dateFrom` in the
    # past would empty the real volume's page too; dropping it keeps the response non-empty, which is
    # the point of validating an item schema.
    "listCompetitionMatches": {"dateFrom": OMIT, "dateTo": OMIT},
    # `minScore` has a documented default (0.3) but no example. On the fake embedder the vectors are
    # unrelated and the default would drop every hit; 0 exercises the item schema instead. On the real
    # model the default is what an agent sends, so the stack sweep keeps it.
    "searchKnowledgeMinScoreFake": {"minScore": 0.0},
}

#: What the *unit* sweep uses; the stack sweep keeps `minScore` at its documented default because the
#: real model's scores are meaningful.
SWEEP_OVERRIDES_UNIT = {**SWEEP_OVERRIDES, "searchKnowledge": SWEEP_OVERRIDES["searchKnowledgeMinScoreFake"]}


def request_for(operation_id: str) -> tuple[str, str, dict[str, Any]]:
    """(method, path, query parameters) for one operation, using its documented examples.

    Query parameters without an example are omitted, so the documented default is exercised.
    """
    return request_for_with(operation_id, overrides={})


def request_for_with(operation_id: str, *, overrides: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Same, but with chosen parameters replaced (or dropped, with `OMIT`)."""
    method, path, operation_node = operation(operation_id)
    params: dict[str, Any] = {}
    for entry in operation_node.get("parameters", []):
        spec = parameter(entry)
        schema = resolve(spec.get("schema", {}))
        if spec["name"] in overrides:
            chosen = overrides[spec["name"]]
            if chosen is not OMIT and spec["in"] != "path":
                params[spec["name"]] = chosen
            continue
        if spec["in"] == "path":
            continue
        if spec.get("required") or "example" in schema:
            params[spec["name"]] = _value(schema)

    for spec in parameters(operation_id):
        if spec["in"] == "path":
            value = overrides.get(spec["name"], _value(resolve(spec.get("schema", {}))))
            path = path.replace("{" + spec["name"] + "}", str(value))
    return method, path, params


# ---------------------------------------------------------------------------------------------
# The seeded database
# ---------------------------------------------------------------------------------------------


@dataclass(slots=True)
class Seeded:
    """What the fixture put in, so a test can name a row instead of guessing an id."""

    now: datetime
    runs: dict[str, str] = field(default_factory=dict)
    turns: dict[str, str] = field(default_factory=dict)
    chunks: list[str] = field(default_factory=list)


def seed_api(session: Session, embedder: Embedder | None = None) -> Seeded:
    """A small but complete world: five competitions, five teams, one finished match per season, two
    standings snapshots, four ingestion runs of different shapes and three agent turns.

    The numbers are chosen so the assertions can be exact rather than "not empty": Arsenal's form
    window is four settled matches (two wins, a draw and a loss), and the head-to-head record against
    Chelsea is one win and one draw.

    Each group is flushed before the next one is added. That is not tidiness: SQLAlchemy orders the
    INSERTs of one flush by mapper creation key and by `relationship()` dependencies, and a plain
    `ForeignKey` column creates neither - so `matches` would go in before `teams` and the database
    would refuse it. The production writers each open a session per row (`ingest/pipeline.py`), which
    is why this never came up there.
    """
    now = datetime.now(UTC)
    seeded = Seeded(now=now)

    session.add_all(
        [
            Competition(
                code=COMPETITION,
                name="Premier League",
                area="England",
                type="LEAGUE",
                current_season=SEASON,
                season_start=date(2026, 8, 14),
                season_end=date(2027, 5, 24),
                coverage_fixtures=True,
                coverage_standings=True,
                coverage_scorers=True,
                coverage_lineups=False,
                coverage_live_scores=False,
                coverage_note="Live scores, odds, lineups and advanced statistics are paid tiers",
            ),
            Competition(
                code=OTHER_COMPETITION,
                name="Bundesliga",
                area="Germany",
                type="LEAGUE",
                current_season=SEASON,
                coverage_fixtures=True,
                coverage_standings=True,
                coverage_scorers=False,
                coverage_lineups=False,
                coverage_live_scores=False,
            ),
            Competition(
                code=GROUP_COMPETITION,
                name="UEFA Champions League",
                area="Europe",
                type="CUP",
                current_season=SEASON,
                coverage_fixtures=True,
                coverage_standings=True,
                coverage_scorers=True,
                coverage_lineups=False,
                coverage_live_scores=False,
            ),
            Competition(
                code=STALE_COMPETITION,
                name="Serie A",
                area="Italy",
                type="LEAGUE",
                current_season=SEASON,
                coverage_fixtures=True,
                coverage_standings=True,
                coverage_scorers=False,
                coverage_lineups=False,
                coverage_live_scores=False,
            ),
            Competition(
                code=NEVER_INGESTED,
                name="FIFA World Cup",
                area="World",
                type="CUP",
                current_season=SEASON,
                coverage_fixtures=True,
                coverage_standings=True,
                coverage_scorers=False,
                coverage_lineups=False,
                coverage_live_scores=False,
            ),
        ]
    )
    session.flush()
    session.add_all(
        [
            Team(
                id=TEAM,
                name="Arsenal FC",
                tla="ARS",
                crest="https://example.test/ars.png",
                area="England",
                founded=1886,
                venue="Emirates Stadium",
                club_colors="Red/White",
            ),
            Team(
                id=OPPONENT,
                name="Chelsea FC",
                tla="CHE",
                crest="https://example.test/che.png",
                area="England",
                founded=1905,
                venue="Stamford Bridge",
                club_colors="Blue/White",
            ),
            Team(id=THIRD, name="Tottenham Hotspur FC", tla="TOT", area="England"),
            Team(id=64, name="FC Bayern München", tla="FCB", area="Germany"),
            Team(id=71, name="Borussia Dortmund", tla="BVB", area="Germany"),
        ]
    )
    session.flush()
    session.add_all(
        [
            TeamCompetition(team_id=TEAM, competition_code=COMPETITION),
            TeamCompetition(team_id=OPPONENT, competition_code=COMPETITION),
            TeamCompetition(team_id=THIRD, competition_code=COMPETITION),
            TeamCompetition(team_id=TEAM, competition_code=GROUP_COMPETITION),
            TeamCompetition(team_id=OPPONENT, competition_code=GROUP_COMPETITION),
            TeamCompetition(team_id=64, competition_code=OTHER_COMPETITION),
            TeamCompetition(team_id=71, competition_code=OTHER_COMPETITION),
        ]
    )
    session.flush()
    # Three players for Arsenal, none for Spurs: `squad_available` has to be able to say both.
    session.add_all(
        [
            Player(id=1000 + index, team_id=TEAM, name=name, position=position, nationality="England")
            for index, (name, position) in enumerate(
                [("David Raya", "Goalkeeper"), ("Bukayo Saka", "Right Winger"), ("Declan Rice", "Central Midfield")]
            )
        ]
    )
    session.flush()

    # Two fixed snapshots, exactly like the standings fixtures above. They used to be `now - 1 day`,
    # which made every assertion about "the latest snapshot" depend on the calendar: the contract
    # sweep sends the documented `snapshot` example, so the suite passed only on the day the example
    # was written. Fixed dates make "latest" a fact of the fixture, not of the clock.
    session.add_all(
        [
            TopScorer(
                competition_code=COMPETITION,
                season=SEASON,
                snapshot_date=date(2026, 11, 1),
                player_id=1001,
                team_id=TEAM,
                played_matches=7,
                goals=5,
                assists=2,
                penalties=1,
            ),
            TopScorer(
                competition_code=COMPETITION,
                season=SEASON,
                snapshot_date=date(2026, 11, 1),
                player_id=1002,
                team_id=TEAM,
                played_matches=7,
                goals=3,
                assists=1,
                penalties=0,
            ),
            TopScorer(
                competition_code=COMPETITION,
                season=SEASON,
                snapshot_date=date(2026, 10, 12),
                player_id=1001,
                team_id=TEAM,
                played_matches=5,
                goals=4,
                assists=1,
                penalties=0,
            ),
            TopScorer(
                competition_code=COMPETITION,
                season=SEASON,
                snapshot_date=date(2026, 10, 12),
                player_id=1002,
                team_id=TEAM,
                played_matches=5,
                goals=2,
                assists=1,
                penalties=0,
            ),
        ]
    )
    session.flush()

    session.add_all(
        [
            Match(
                id=MATCH_ID,
                competition_code=COMPETITION,
                season=SEASON,
                matchday=5,
                stage="REGULAR_SEASON",
                status="FINISHED",
                utc_date=datetime(2026, 3, 15, 15, 0, tzinfo=UTC),
                home_team_id=TEAM,
                away_team_id=OPPONENT,
                score_winner="HOME_TEAM",
                score_duration="REGULAR",
                score_full_time_home=2,
                score_full_time_away=1,
                score_half_time_home=1,
                score_half_time_away=0,
                venue="Emirates Stadium",
                referees=[{"id": 1, "name": "Michael Oliver", "type": "REFEREE", "nationality": "England"}],
                last_updated=datetime(2026, 10, 11, 12, 40, tzinfo=UTC),
            ),
            Match(
                id=419824,
                competition_code=COMPETITION,
                season=SEASON,
                matchday=6,
                stage="REGULAR_SEASON",
                status="FINISHED",
                utc_date=datetime(2026, 4, 1, 14, 0, tzinfo=UTC),
                home_team_id=OPPONENT,
                away_team_id=THIRD,
                score_winner="DRAW",
                score_duration="REGULAR",
                score_full_time_home=0,
                score_full_time_away=0,
                last_updated=datetime(2026, 10, 11, 12, 41, tzinfo=UTC),
            ),
            Match(
                id=419825,
                competition_code=COMPETITION,
                season=SEASON,
                matchday=7,
                stage="REGULAR_SEASON",
                status="FINISHED",
                utc_date=datetime(2026, 4, 20, 15, 0, tzinfo=UTC),
                home_team_id=THIRD,
                away_team_id=TEAM,
                score_winner="HOME_TEAM",
                score_duration="REGULAR",
                score_full_time_home=3,
                score_full_time_away=1,
                last_updated=datetime(2026, 10, 11, 12, 42, tzinfo=UTC),
            ),
            Match(
                id=419826,
                competition_code=COMPETITION,
                season=SEASON,
                matchday=8,
                stage="REGULAR_SEASON",
                status="FINISHED",
                utc_date=datetime(2026, 5, 5, 15, 0, tzinfo=UTC),
                home_team_id=TEAM,
                away_team_id=THIRD,
                score_winner="HOME_TEAM",
                score_duration="REGULAR",
                score_full_time_home=4,
                score_full_time_away=2,
                last_updated=datetime(2026, 10, 11, 12, 43, tzinfo=UTC),
            ),
            # A fixture: no score at all, so the response must omit `score` rather than send nulls
            # where the contract says integer, and `last_updated` is null because the provider has
            # not stamped it yet.
            Match(
                id=419830,
                competition_code=COMPETITION,
                season=SEASON,
                matchday=12,
                stage="REGULAR_SEASON",
                status="SCHEDULED",
                utc_date=datetime(2026, 11, 20, 15, 0, tzinfo=UTC),
                home_team_id=TEAM,
                away_team_id=OPPONENT,
            ),
            # The previous season, which the default (current-season) filter must keep out.
            Match(
                id=419840,
                competition_code=COMPETITION,
                season=2025,
                matchday=3,
                stage="REGULAR_SEASON",
                status="FINISHED",
                utc_date=datetime(2025, 3, 10, 15, 0, tzinfo=UTC),
                home_team_id=OPPONENT,
                away_team_id=TEAM,
                score_winner="DRAW",
                score_duration="REGULAR",
                score_full_time_home=1,
                score_full_time_away=1,
                last_updated=datetime(2026, 10, 11, 12, 44, tzinfo=UTC),
            ),
            Match(
                id=419850,
                competition_code=OTHER_COMPETITION,
                season=SEASON,
                matchday=5,
                stage="REGULAR_SEASON",
                status="FINISHED",
                utc_date=datetime(2026, 3, 20, 17, 30, tzinfo=UTC),
                home_team_id=64,
                away_team_id=71,
                score_winner="HOME_TEAM",
                score_duration="REGULAR",
                score_full_time_home=2,
                score_full_time_away=0,
                last_updated=datetime(2026, 10, 11, 12, 45, tzinfo=UTC),
            ),
        ]
    )
    session.flush()

    session.add_all(
        [
            # The newest snapshot, then the one before it.
            *[
                Standing(
                    competition_code=COMPETITION,
                    season=SEASON,
                    snapshot_date=date(2026, 11, 1),
                    stage="REGULAR_SEASON",
                    table_type="TOTAL",
                    team_id=team_id,
                    position=position,
                    played=12,
                    won=8,
                    drawn=2,
                    lost=2,
                    goals_for=24,
                    goals_against=10,
                    goal_difference=14,
                    points=26 - position,
                    form="WWDWW",
                )
                for position, team_id in enumerate([TEAM, OPPONENT, THIRD], start=1)
            ],
            *[
                Standing(
                    competition_code=COMPETITION,
                    season=SEASON,
                    snapshot_date=date(2026, 10, 12),
                    stage="REGULAR_SEASON",
                    table_type="TOTAL",
                    team_id=team_id,
                    position=position,
                    played=10,
                    won=6,
                    drawn=2,
                    lost=2,
                    goals_for=18,
                    goals_against=9,
                    goal_difference=9,
                    points=20 - position,
                    form="WWDWL",
                )
                for position, team_id in enumerate([TEAM, OPPONENT, THIRD], start=1)
            ],
            # Home and away splits of the newest snapshot: stored, never served.
            *[
                Standing(
                    competition_code=COMPETITION,
                    season=SEASON,
                    snapshot_date=date(2026, 11, 1),
                    stage="REGULAR_SEASON",
                    table_type=split,
                    team_id=team_id,
                    position=position,
                    played=6,
                    won=4,
                    drawn=1,
                    lost=1,
                    goals_for=12,
                    goals_against=5,
                    goal_difference=7,
                    points=13,
                )
                for split in ("HOME", "AWAY")
                for position, team_id in enumerate([TEAM, OPPONENT, THIRD], start=1)
            ],
            # A grouped table, to show the group label being echoed when every row agrees on one.
            *[
                Standing(
                    competition_code=GROUP_COMPETITION,
                    season=SEASON,
                    snapshot_date=date(2026, 11, 1),
                    stage="LEAGUE_STAGE",
                    group_label="GROUP_A",
                    table_type="TOTAL",
                    team_id=team_id,
                    position=position,
                    played=6,
                    won=4,
                    drawn=1,
                    lost=1,
                    goals_for=11,
                    goals_against=4,
                    goal_difference=7,
                    points=13,
                )
                for position, team_id in enumerate([TEAM, OPPONENT], start=1)
            ],
        ]
    )
    session.flush()

    # Four runs, each shaped like something the real ledger contains. `r_measurement` is the
    # score-delay poll: status succeeded, one call, and NO competition scope - which must refresh
    # nothing (`backend/services/freshness.py`).
    seeded.runs["success"] = _run(
        session,
        started=now - timedelta(hours=3),
        finished=now - timedelta(hours=2, minutes=50),
        status="succeeded",
        trigger="manual",
        competitions=[COMPETITION, OTHER_COMPETITION, GROUP_COMPETITION, "EC"],
        calls_used=162,
        rate_limit_hits=1,
        rows=(900, 10, 5),
        duration_seconds=600.0,
    )
    seeded.runs["partial"] = _run(
        session,
        started=now - timedelta(minutes=90),
        finished=now - timedelta(minutes=85),
        status="partial",
        trigger="schedule",
        competitions=[COMPETITION, "EC"],
        calls_used=54,
        rows=(100, 2, 0),
        duration_seconds=300.5,
        errors=[
            {
                "resource": "standings:EC",
                "message": "upstream returned HTTP 404 (resource not found) for /competitions/EC/standings",
            },
            {"resource": "matches:2024-06-14..2024-09-11", "message": "upstream returned HTTP 400 for /matches"},
        ],
    )
    seeded.runs["measurement"] = _run(
        session,
        started=now - timedelta(minutes=30),
        finished=now - timedelta(minutes=29),
        status="succeeded",
        trigger="manual",
        competitions=None,
        calls_used=10,
        duration_seconds=60.0,
    )
    seeded.runs["failed"] = _run(
        session,
        started=now - timedelta(minutes=20),
        finished=now - timedelta(minutes=19),
        status="failed",
        trigger="manual",
        competitions=[OTHER_COMPETITION],
        errors=[{"resource": "run", "message": "operator stopped the container mid-run"}],
    )
    seeded.runs["old"] = _run(
        session,
        started=now - timedelta(days=60),
        finished=now - timedelta(days=60) + timedelta(minutes=10),
        status="succeeded",
        trigger="schedule",
        competitions=[STALE_COMPETITION],
        calls_used=130,
        rows=(500, 0, 0),
        duration_seconds=900.0,
    )

    seeded.turns["tool"] = _turn(
        session,
        created_at=now - timedelta(hours=2),
        user_message="Where are Arsenal in the Premier League?",
        answer="Arsenal are top of the Premier League as of 2026-10-11T12:43:00Z, source: football-data.org.",
        grounded=True,
        route="tool",
        route_source="rules",
        review_status="correct",
        tool_calls=[
            {
                "name": "get_standings",
                "status": "ok",
                "args_summary": {"competition": COMPETITION},
                "latency_ms": 12,
                "policy_decision": "allowlisted",
            }
        ],
        data_as_of=datetime(2026, 10, 11, 12, 43, tzinfo=UTC),
    )
    seeded.turns["knowledge"] = _turn(
        session,
        created_at=now - timedelta(hours=1),
        user_message="Why are your scores a few minutes behind?",
        answer="Scores come from the free tier, which delivers them a couple of minutes late.",
        grounded=True,
        route="knowledge",
        route_source="rules",
        review_status="unreviewed",
        # One well-formed call and one that cannot be described: the second must not reach a client,
        # because `ToolCall` requires a name and a status.
        tool_calls=[
            {"name": "search_knowledge", "status": "ok", "args_summary": {"q": "free tier delay"}},
            {"name": "broken"},
        ],
    )
    seeded.turns["model_route"] = _turn(
        session,
        created_at=now - timedelta(minutes=45),
        user_message="What was the score in the north London derby?",
        answer="I do not have that match.",
        grounded=False,
        route="refuse",
        route_source="model",
        route_confidence=0.62,
        review_status="flagged",
        review_note="refused a fixture that was in the database under a different name",
        model="hermes-3-405b",
        latency_ms=1800,
    )

    if embedder is not None:
        # The corpus note M2 indexes, with embeddings from the same embedder the app will search
        # with, so the search endpoint can be exercised without Ollama.
        source_file = "policy/free-tier-delay-and-coverage.md"
        passages = [
            (
                "What the free plan gives us",
                "The free plan gives us fixtures, results, league tables, squads and top scorers.",
            ),
            (
                "How old the data is",
                "Scores arrive delayed by roughly one and a half to three minutes on the free tier.",
            ),
        ]
        vectors = embedder.embed_documents([text for _, text in passages], titles=["Free tier"] * len(passages))
        for ordinal, ((heading, text), vector) in enumerate(zip(passages, vectors, strict=True)):
            chunk_id = new_id()
            seeded.chunks.append(chunk_id)
            session.add(
                KnowledgeChunk(
                    id=chunk_id,
                    source_file=source_file,
                    heading=heading,
                    ordinal=ordinal,
                    chunk_text=text,
                    embedding=vector,
                    embedding_model=embedder.model,
                    embedding_dim=embedder.dim,
                    content_hash="a" * 64,
                )
            )

    session.commit()
    return seeded


def _run(
    session: Session,
    *,
    started: datetime,
    finished: datetime | None,
    status: str,
    trigger: str,
    competitions: list[str] | None = None,
    calls_used: int | None = None,
    rate_limit_hits: int | None = None,
    rows: tuple[int, int, int] | None = None,
    errors: list[dict[str, Any]] | None = None,
    duration_seconds: float | None = None,
) -> str:
    run_id = new_id()
    session.add(
        IngestRun(
            id=run_id,
            started_at=started,
            finished_at=finished,
            status=status,
            trigger=trigger,
            competitions=competitions,
            calls_used=calls_used,
            rate_limit_hits=rate_limit_hits,
            rows_inserted=rows[0] if rows else None,
            rows_updated=rows[1] if rows else None,
            rows_unchanged=rows[2] if rows else None,
            errors=errors if errors is not None else [],
            duration_seconds=duration_seconds,
        )
    )
    return run_id


def _turn(
    session: Session,
    *,
    created_at: datetime,
    user_message: str,
    answer: str,
    grounded: bool,
    route: str,
    route_source: str,
    review_status: str,
    route_confidence: float | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    review_note: str | None = None,
    model: str | None = None,
    latency_ms: int | None = None,
    data_as_of: datetime | None = None,
) -> str:
    turn_id = new_id()
    session.add(
        AgentTurn(
            id=turn_id,
            chat_id_hash="salted-hash",
            user_message=user_message,
            tool_calls=tool_calls,
            answer=answer,
            grounded=grounded,
            data_as_of=data_as_of,
            model=model,
            latency_ms=latency_ms,
            review_status=review_status,
            review_note=review_note,
            route=route,
            route_source=route_source,
            route_confidence=route_confidence,
            created_at=created_at,
        )
    )
    return turn_id
