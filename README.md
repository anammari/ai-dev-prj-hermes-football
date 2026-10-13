# Hermes Football

A Telegram agent that answers football questions **accurately** — grounded in a local database refreshed daily from
football-data.org, with a read-only tool layer, an evaluation harness, and a dashboard that shows whether any of it is
actually working. Everything runs locally in Docker Compose; there is no server to rent.

Status: **M1–M2 done, M3 next** (see the [milestone tracker](#milestone-tracker)).

## Problem description

Football answers are easy to find and often wrong: scores are delayed, tables are stale, and a confident model will
invent both. This bot answers questions about fixtures, results, standings and competition rules from the free
football-data.org API plus a small hand-written English knowledge corpus, and it carries the data timestamp on every
answer. When the data does not support an answer — an unanswerable question, a competition the free plan does not
cover, a match not yet played — it says so instead of guessing. Predictions, betting and live scores are explicit
non-goals.

In plain language: [`_docs/scoping.md`](_docs/scoping.md). As requirements:
[`_docs/product-spec.md`](_docs/product-spec.md).

## API contract

Written down before it is implemented: [`openapi.yaml`](openapi.yaml) (v0.1.0) is the source of truth for what the API
serves. `make validate-spec` lints it, `make swagger` serves it, and
[`tests/test_contract_coverage.py`](tests/test_contract_coverage.py) fails when the contract and the database schema
drift apart in either direction. The backend that implements it arrives with M3; the gap already known — the route
fields on `AgentTurn` — is recorded in [`_docs/data-model.md`](_docs/data-model.md).

## Database schema

PostgreSQL 16 with pgvector in the stack, SQLite in development, on one code path, with Alembic migrations applied on
startup. The schema includes the notes index with `vector(768)` and an HNSW index for similarity search, plus bronze
upstream payloads and normalized scorer snapshots.

- Tables: [`db/models.py`](db/models.py), created by
  [`db/migrations/versions/0001_init.py`](db/migrations/versions/0001_init.py) and
  [`db/migrations/versions/0002_ingestion_storage.py`](db/migrations/versions/0002_ingestion_storage.py)
- Table by table, with the mapping onto the contract and the open items: [`_docs/data-model.md`](_docs/data-model.md)
- Notes corpus the index is built from: [`hermes/agent-knowledge/manifest.yaml`](hermes/agent-knowledge/manifest.yaml)

## Integration testing

[`tests/integration/`](tests/integration) holds the tests that need the real stack — PostgreSQL + pgvector, the
embedding model in the `ollama` container, the read-only role — and they are kept out of the fast unit run.
`make test` runs the unit tests, `make itest` runs these against the running stack, and both run in containers rather
than on the host. Schema, corpus, chunker and indexer checks live in [`tests/`](tests).

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

## Commands

Everything runs in containers: apart from Docker, this repository and a `.env`, nothing is installed on the host.

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
| `make score-delay [MATCH_ID=…]` | Poll a finished scoreless match and record score-availability delay |
| `make lint` | Ruff over the repository |
| `make check-notes` / `make index-notes` | Validate the notes corpus against its manifest / index the changed notes |
| `make search Q="…"` | Ask the corpus a question and see the passages it would retrieve |
| `make db-port` | Also publish the database on the host, for development only |
| `make logs S=db` | Tail one service's logs |
| `make swagger` / `make swagger-stop` / `make validate-spec` | Serve, stop and lint the API contract |

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
