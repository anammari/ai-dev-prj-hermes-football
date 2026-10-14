# Hermes Football

A Telegram agent that answers football questions **accurately** — grounded in a local database refreshed daily from
football-data.org, with a read-only tool layer, an evaluation harness, and a dashboard that shows whether any of it is
actually working. Everything runs locally in Docker Compose; there is no server to rent.

Status: **M1–M3 done** (see the [milestone tracker](#milestone-tracker)); next is the M3b router spike.

## How this README maps to the course criteria

One section per course criterion, in the order the criteria are assessed, so a marker can walk the list from top to
bottom. The numbers below are **criterion numbers, not milestones** — the milestones (M0–M6) are at the
[milestone tracker](#milestone-tracker). The full mapping, including the files each criterion points at, is
[`_docs/scoping.md`](_docs/scoping.md) §7.

Where a criterion is not built yet its section says so plainly and names the milestone that delivers it, rather than
reading as if it were finished.

## 1. Problem Description

Football answers are easy to find and often wrong: scores are delayed, tables are stale, and a confident model will
invent both. This bot answers questions about fixtures, results, standings and competition rules from the free
football-data.org API plus a small hand-written English knowledge corpus, and it carries the data timestamp on every
answer. When the data does not support an answer — an unanswerable question, a competition the free plan does not
cover, a match not yet played — it says so instead of guessing. Predictions, betting and live scores are explicit
non-goals.

In plain language: [`_docs/scoping.md`](_docs/scoping.md). As requirements:
[`_docs/product-spec.md`](_docs/product-spec.md).

## 2. AI-Assisted Development Workflow

Three artefacts, all kept in the repository rather than thrown away:

- [`prompts/`](prompts/README.md) — the versioned prompt bank used while building, so the prompts are reviewable like
  code instead of living in a chat window.
- [`AGENTS.md`](AGENTS.md) — durable instructions that every AI assistant working here reads first, including the ten
  hard rules (grounding over fluency, freshness on every answer, the 10-request budget, a read-only agent data path,
  secrets never in a prompt).
- [`_docs/ai-usage-report.md`](_docs/ai-usage-report.md) — the running log of what was delegated to an agent, what a
  human reviewed, what was rejected, and which tests prove it. Session S5 covers the M2 build and, in particular, the
  three defects that only a live upstream run exposed.

## 3. Technologies and System Architecture

The target component diagram (Telegram → `hermes` → `mcp-server` → `backend` → `ingest` → PostgreSQL + `ollama`) and
the stack are in [`AGENTS.md`](AGENTS.md) §Architecture. The plain-language version is
[`_docs/scoping.md`](_docs/scoping.md) §1, with the "where it runs and why not on a hosted GPU" argument in §6.

Standing technology decisions are recorded rather than assumed, in [`_docs/decisions/`](_docs/decisions/README.md):
the notes corpus and its manifest, the embedding model, the prompt-router spike, and the embedding tag that runs in
the container.

A dedicated `_docs/architecture.md` is scheduled with **M6**; until then `AGENTS.md` is the source of truth for the
architecture.

## 4. Frontend Implementation

**Not built — arrives with M5.** The dashboard (data freshness, fixtures and standings, the agent log, eval results,
admin controls) is specified in [`_docs/product-spec.md`](_docs/product-spec.md). It will be a Next.js/TypeScript app
with a single typed API client, Vitest + Testing Library unit tests and Playwright end-to-end tests. Neither
`frontend/` nor `tests/e2e/` exists yet.

## 5. API Contract

Written down before it is implemented: [`openapi.yaml`](openapi.yaml) is the source of truth for what the API serves.
`make validate-spec` lints it, `make swagger` serves it, and it is checked in both directions by tests that read the
file rather than a copy of it:

| Test | What it would catch |
| --- | --- |
| [`tests/test_contract_coverage.py`](tests/test_contract_coverage.py) | A contract field with nowhere to live in `db/models.py`, or a column no contract property asks for |
| [`tests/test_api_contract.py`](tests/test_api_contract.py) | **Drift between the code and the contract.** A route the contract does not declare, a documented operation with no route, a renamed or removed response field, a changed parameter name, requiredness *or bound*, an `operationId` reused by a second route, a version bump on one side only. The validator itself is tested, so the check cannot silently pass by accepting everything |
| [`tests/integration/test_backend_stack.py`](tests/integration/test_backend_stack.py) | The same sweep on real Postgres, where `JSON`, `numeric` and `vector(768)` behave differently from SQLite — with the ids read from the volume rather than taken from the contract's examples, so the path parameters are exercised too |

Five details are worth naming, because each closes a way the suite could have passed while the API drifted:

- **Routes are read from the router tree, not from the generated document.** FastAPI leaves a route registered with
  `include_in_schema=False` out of `app.openapi()`, so a route that is served but undocumented used to be invisible to
  the whole suite — an adversarial review added one to the unauthenticated router and everything passed. The coverage
  test now walks `app.router` and compares operation *and* path template, and it fails on a repeated `operationId`
  (which would otherwise shadow a route in every mapping keyed by operation id).
- **Parameter schemas are compared, not just their names.** `limit: Query(ge=1, le=100) = 20` against a contract saying
  `maximum: 200, default: 50` used to pass while rejecting a request the contract allows; the test now compares type,
  bounds, format, pattern and default. The only exemptions are narrow and one-directional: the app may spell a declared
  `format: int64` as its range, and OpenAPI's `format: float` on a number is not a constraint any validator enforces.
- **The validator carries every constraint the contract uses.** `minItems` was missing from the translation, so the
  contract's "exactly two teams" went unchecked; a meta-test now walks the file and fails on any constraint keyword the
  translator would drop.
- **Enums are checked as behaviour.** The app does not restate the contract's enum lists in Python — it reads them from
  the file at request time — so the test that matters sends a value the file does not list to every enum parameter and
  expects a `400` naming the parameter.
- **The check that the API cannot reach upstream reads the deployment too.** `docker-compose.yml` is asserted to give the
  `backend` service no provider key, no Docker socket, read-only corpus mounts, and the only published port.

The contract is also *served*, verbatim, at `/openapi.yaml`, and Swagger UI at `/docs` renders that file — so a
reviewer can diff the deployed API against this repository, and the app cannot serve a shape it does not implement.
FastAPI's own generated document is switched off (`/openapi.json` answers 404); it is used only *inside* the tests, as
the app's honest statement of what it registers. Contract changes that need behaviour stay in the same commit:
v0.2.0 added the three routing fields to `AgentTurn` (`AGENTS.md` rule 10) together with the columns that fill them, and
declared `format: int64` on the provider ids and `offset` in the same commit that turned an out-of-range id from a
client-reachable `500` into the documented `400`.

## 6. Backend Implementation

[`backend/`](backend) is a FastAPI service built against that contract, reading PostgreSQL through a session that
logs in as the read-only role. Fourteen `GET` operations are implemented; the two `POST`/`PATCH` admin operations are
declared and *intentionally* answer a contract-shaped 404 naming the milestone that implements them, so the contract
has no silent holes (`backend/routers/admin.py`). The layering is one directory per concern:

```text
backend/app.py            create_app(): routers, lifespan, error handlers, request ids
backend/routers/          one module per tag; validate, call a service, attach meta - no SQL, no logic
backend/services/         the queries and the arithmetic (records, form, freshness)
backend/schemas.py        row -> contract shape, and the pruning rules that keep nulls out
backend/contract.py       the loaded contract, used to reject values its own enums do not allow
backend/db.py             the read-only engine (rule 4); no write engine exists in M3
backend/errors.py         the contract's error envelope: 400/401/404/500/503
```

Things worth knowing before reading the code:

- **Freshness is a first-class answer** (rule 2): every response carries `meta.data_as_of`, the provider's own
  `lastUpdated` for match data and the snapshot's write time for a table — never the row's write time pretending to be
  the data's age. `/meta/freshness` derives the whole picture from the run ledger: a run with no competition scope
  refreshes nothing, a competition the ledger merely *listed* is not fresh unless rows were actually stored for it,
  and a run stamped in the future (container clock skew) is ignored rather than shown as a negative age.
- **"Not covered" is not "not found".** A competition with nothing ingested answers `503 data_not_available`
  ("no data"), a missing season or snapshot answers `404` ("no such resource"), and a filter that matches nothing
  answers `200` with an empty list. The contract spells this out; the code follows it literally.
- **No upstream access from a request** (rule 3): the API has no HTTP client and no provider credential, and
  [`tests/test_api_security.py`](tests/test_api_security.py) enforces it three ways — it whitelists what `backend/` may
  import from `ingest` (the corpus reader and one pure schedule function), follows those modules' own imports so the
  upstream client cannot come back transitively, and checks the Compose service definition for a provider key.
- **Nothing to leak**: one error envelope for every failure, no exception text in a 500, request ids on every
  response, and the bearer token compared in constant time and never echoed.

Run it against the stack with `make up` and read the contract at <http://localhost:8000/docs>, or
`docker compose logs -f backend`. `make test` covers the API on SQLite; `make itest` repeats it on Postgres.

## 7. Database Integration

PostgreSQL 16 with pgvector in the stack, SQLite in development, on one code path, with Alembic migrations applied on
startup. The schema includes the notes index with `vector(768)` and an HNSW index for similarity search, plus bronze
upstream payloads and normalized scorer snapshots.

- Tables: [`db/models.py`](db/models.py), created by
  [`db/migrations/versions/0001_init.py`](db/migrations/versions/0001_init.py) and
  [`db/migrations/versions/0002_ingestion_storage.py`](db/migrations/versions/0002_ingestion_storage.py)
- Table by table, with the mapping onto the contract and the open items: [`_docs/data-model.md`](_docs/data-model.md)
- Notes corpus the index is built from: [`hermes/agent-knowledge/manifest.yaml`](hermes/agent-knowledge/manifest.yaml)

## 8. Containerization

Everything runs in containers. [`docker-compose.yml`](docker-compose.yml) defines the services, the volumes and the
health checks; the [`Makefile`](Makefile) is the only entry point; and secrets arrive from `.env` at run time rather
than being baked into an image layer.

`make up` starts what exists today — `db`, `ollama`, the `backend` API and the daily `ingest` scheduler — and applies
the migrations. `mcp-server`, `hermes`, `frontend` and the observability stack join as their milestones land. Dependencies are gated on health (`db` and `ollama` are both `service_healthy`), and the Compose project name is
overridable through `COMPOSE_PROJECT_NAME` so a second checkout cannot collide with this one on the same volume.

The model server is a derived image rather than the stock upstream one. `ollama/ollama:0.40.2` is 7.05 GB, about
3.6 GB of which is four CUDA trees that a container on Apple Silicon can never load, so [`Dockerfile.ollama`](Dockerfile.ollama)
deletes them and flattens the result into a single layer — a `RUN rm` on its own would reclaim nothing, because the
bytes stay in the layer below. The stack runs the same Ollama version (0.40.2) at **637 MB**. The reasoning, including
what a GPU host would have to change, is [decision 0005](_docs/decisions/0005-ollama-image.md).

## 9. Integration Testing

[`tests/integration/`](tests/integration) holds the tests that need the real stack — PostgreSQL + pgvector, the
embedding model in the `ollama` container, the read-only role — and they are kept out of the fast unit run.

`make test` runs the unit tests, `make itest` runs these against the running stack, and both run in containers rather
than on the host. `make itest-isolated` runs the same tests against a throwaway Compose project with its own database,
volumes and passwords, and tears it down afterwards, for when the retained volume must not be touched. Schema, corpus,
chunker and indexer checks live in [`tests/`](tests).

## 10. Deployment

**Not built — arrives with M6.** The bot itself is the public interface, using long polling so there are no inbound
ports, and the dashboard is exposed through a Cloudflare tunnel. `_docs/deployment.md` will record the addresses and
the post-deploy check. There is deliberately no VPS and no cloud host; the reasoning is in
[`_docs/scoping.md`](_docs/scoping.md) §6.

## 11. CI/CD Pipeline

**Not built — arrives with M6.** `.github/workflows/` will run lint, the unit and integration tests and the
answer-quality scoreboard on every pull request; merging to `main` will deploy, verify and be able to roll back.
Until then the same checks run locally and are documented under [criterion 14](#14-reproducibility).

## 12. Agent Extension Pack

**Partially in place.** The agent's durable instructions live in [`AGENTS.md`](AGENTS.md), and the first hand-written
notes are in [`hermes/agent-knowledge/`](hermes/agent-knowledge/manifest.yaml) — competition formats, tiebreakers, a
glossary, and the free-tier data policy. The reusable skills, the `answer-verifier` subagent, the read-only MCP tool
server, the hooks and the guardrails arrive with **M4–M6**: `skills/`, `subagents/`, `mcp-server/` and `hooks/` do not
exist yet. Every capability will be declared in `docs/permissions.md` before it ships (rule 8) — an undocumented
capability is not shippable.

## 13. Security, Audit, and DevOps Hardening

**Partially in place.** The data policy is written and indexed as a note —
[`free-tier-delay-and-coverage.md`](hermes/agent-knowledge/policy/free-tier-delay-and-coverage.md) — so the bot can
explain its own freshness and coverage limits instead of guessing.

The security posture is already fixed by the hard rules in [`AGENTS.md`](AGENTS.md): a read-only database role for
everything the agent can reach, no Docker socket inside the Hermes container, secrets never in the repository or a
prompt, Telegram input treated as untrusted, and no capability left undeclared.

**M6** adds the rest: `security/` (scanner findings and the capability + threat tables), `ops/` (runbooks and an
incident rehearsal), `observability/` (OTel collector → Prometheus, Loki, Tempo, Grafana, with one alert that fires on
real user impact), and the AI code-review on pull requests.

## 14. Reproducibility

Three commands take a clean machine to a working stack — which is the criterion's own test — after one edit:

```bash
make setup     # create .env from .env.example, build the app image
# put a football-data.org token in UPSTREAM_API_KEY inside .env (free signup)
make up        # start db and ollama, pull the embedding model, migrate, start the API and the scheduler
make test      # unit tests
```

`make up` also serves the API on <http://localhost:8000> (`/docs` for the interactive contract). Its bearer token is
`API_AGENT_TOKEN` in `.env`; an empty one is not an open door — the app refuses every agent-facing request and says
so in the log.

`make setup` copies `.env.example` verbatim, and its `UPSTREAM_API_KEY` is a placeholder. The scheduler and every
manual collection refuse to start on a placeholder rather than fail at the first scheduled run, so until a real token
is in `.env`, `make up` stops with `ingest scheduler exited at startup`. On a fresh `ollama` volume `make up` also
pulls the pinned embedding model, so indexing works on the first scheduled run instead of ending `partial` until
someone runs `make models` by hand.

`make itest` then adds the real-stack tests. Apart from Docker, this repository and a `.env`, nothing is installed on
the host.

| Command | What it does |
| --- | --- |
| `make setup` | Create `.env` from `.env.example`, build the app image |
| `make build` | Rebuild the image after changing `db/`, `ingest/` or `tests/` |
| `make up` / `make down` | Start `db`, `ollama`, the `backend` API and the daily ingest scheduler, apply migrations / stop everything |
| `make migrate` | Apply the Alembic migrations |
| `make models` | Pull the pinned embedding model into the `ollama` volume |
| `make test` / `make itest` | Unit tests (fast, no stack) / integration tests against the running stack (the suite reads, never writes) |
| `make itest-isolated` | Integration tests against a throwaway Compose project (own db, ollama, passwords), torn down afterwards |
| `make ingest` | Trigger a manual upstream collection run (requires `UPSTREAM_API_KEY` in `.env`) |
| `make score-delay [MATCH_ID=…]` | Poll a live or recent match and report how old the provider's data is (the `lastUpdated` to fetch gap) |
| `make lint` | Ruff over the repository |
| `make check-notes` / `make index-notes` | Validate the notes corpus against its manifest / index the changed notes |
| `make search Q="…"` | Ask the corpus a question and see the passages it would retrieve |
| `make db-port` | Also publish the database on the host, for development only |
| `make logs S=db` | Tail one service's logs |
| `make swagger` / `make swagger-stop` / `make validate-spec` | Serve, stop and lint the API contract |

If buildx cannot write its state directory (a locked-down or sandboxed machine), prefix a build with
`DOCKER_BUILDKIT=0` — documented in [`AGENTS.md`](AGENTS.md).

## Milestone tracker

| M# | Item | Status |
| --- | --- | --- |
| M0 | Empty repo, scope, product spec, API contract (v0.1.0, lint clean) | Done |
| M1 | Database schema and the first migration, matching the contract: notes table with `vector(768)`, the corpus `manifest.yaml` and the local embedding provider | Done |
| M2 | Daily ingestion from football-data.org: run ledger, idempotent loads, re-indexing changed notes, measured score delay | Done |
| M3 | Backend API against `openapi.yaml`: 14 operations, read-only role, freshness report, `/docs` and a drift test | Done |
| M3b | Router spike: deterministic-first vs model-first, judged against hand-checked expectations, before M4 | Not started |
| M4 | Telegram agent: `SOUL.md`, first notes authored and reviewed, routing, refusal and freshness behaviour | Not started |
| M5 | Dashboard and eval scoreboard, including routing accuracy | Not started |
| M6 | CI/CD, observability, security, AI-usage report | Not started |

Each milestone's meaning and "done when" are stated in two places: [`_docs/scoping.md`](_docs/scoping.md) §8 in plain
language, and [`_docs/product-spec.md`](_docs/product-spec.md) §8 as requirements.

## Project documents

- [`_docs/scoping.md`](_docs/scoping.md) — start here: what we are building, what the free API actually allows, and
  how the 14 course criteria are covered
- [`_docs/product-spec.md`](_docs/product-spec.md) — requirements, acceptance criteria, data model
- [`_docs/data-model.md`](_docs/data-model.md) — the tables, how they map onto the contract, and what is still open
- [`openapi.yaml`](openapi.yaml) — the API contract, written before the code
- [`_docs/decisions/`](_docs/decisions/README.md) — standing decisions: notes corpus, embedding model, router
- [`AGENTS.md`](AGENTS.md) — durable context and the hard rules for anyone (or anything) working here
- [`_docs/ai-usage-report.md`](_docs/ai-usage-report.md) — what was delegated to agents, what a human caught
- [`prompts/`](prompts/README.md) — the versioned prompt bank
