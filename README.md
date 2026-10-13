# Hermes Football

A Telegram agent that answers football questions **accurately** — grounded in a local database refreshed daily from
football-data.org, with a read-only tool layer, an evaluation harness, and a dashboard that shows whether any of it is
actually working. Everything runs locally in Docker Compose; there is no server to rent.

Status: **M1–M2 done, M3 next** (see the [milestone tracker](#milestone-tracker)).

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

Written down before it is implemented: [`openapi.yaml`](openapi.yaml) (v0.1.0) is the source of truth for what the API
serves. `make validate-spec` lints it, `make swagger` serves it, and
[`tests/test_contract_coverage.py`](tests/test_contract_coverage.py) fails when the contract and the database schema
drift apart in either direction. The backend that implements it arrives with M3; the gap already known — the route
fields on `AgentTurn` — is recorded in [`_docs/data-model.md`](_docs/data-model.md).

## 6. Backend Implementation

**Not built — arrives with M3.** The layered FastAPI service that implements the contract does not exist yet;
`backend/` is scheduled for M3. The contract-first discipline is already enforced in the meantime, because
[`tests/test_contract_coverage.py`](tests/test_contract_coverage.py) fails when the schema and the contract diverge.

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

`make up` starts the three services that exist today — `db`, `ollama` and the daily `ingest` scheduler — and applies
the migrations. `backend`, `mcp-server`, `hermes`, `frontend` and the observability stack join as their milestones
land. Dependencies are gated on health (`db` and `ollama` are both `service_healthy`), and the Compose project name is
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
make up        # start db and ollama, pull the embedding model, migrate, start the scheduler
make test      # unit tests
```

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
| `make up` / `make down` | Start `db`, `ollama` and the daily ingest scheduler, apply migrations / stop everything |
| `make migrate` | Apply the Alembic migrations |
| `make models` | Pull the pinned embedding model into the `ollama` volume |
| `make test` / `make itest` | Unit tests (fast, no stack) / integration tests against the running stack |
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
| M3 | Backend API against `openapi.yaml` | Next |
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
