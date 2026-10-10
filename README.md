# Hermes Football

A Telegram agent that answers football questions **accurately** — grounded in a local database refreshed daily from
football-data.org, with a read-only tool layer, an evaluation harness, and a dashboard that shows whether any of it is
actually working. Everything runs locally in Docker Compose; there is no server to rent.

Status: **M1**. The specs, the API contract (v0.1.0), the decision records, the database schema with its first
migration, the notes corpus and its local embedding provider exist and are tested. No API or agent code yet.

## Milestone tracker

| M# | Item | Status |
| --- | --- | --- |
| M0 | Empty repo, scope, product spec, API contract (v0.1.0, lint clean) | Done |
| M1 | Database schema and the first migration, matching the contract: notes table with `vector(768)`, the corpus `manifest.yaml` and the local embedding provider | Done |
| M2 | Daily ingestion from football-data.org: run ledger, idempotent loads, re-indexing changed notes, measured score delay | Next |
| M3 | Backend API against `openapi.yaml` | Not started |
| M3b | Router spike: deterministic-first vs model-first, judged against hand-checked expectations, before M4 | Not started |
| M4 | Telegram agent: `SOUL.md`, first notes authored and reviewed, routing, refusal and freshness behaviour | Not started |
| M5 | Dashboard and eval scoreboard, including routing accuracy | Not started |
| M6 | CI/CD, observability, security, AI-usage report | Not started |

Each milestone's meaning and "done when" are stated in two places: [`_docs/scoping.md`](_docs/scoping.md) §8 in plain
language, and [`_docs/product-spec.md`](_docs/product-spec.md) §8 as requirements.

## Read next

- [`_docs/scoping.md`](_docs/scoping.md) — start here: what we are building, what the free API actually allows, and
  how the 14 course criteria are covered
- [`_docs/product-spec.md`](_docs/product-spec.md) — requirements, acceptance criteria, data model
- [`_docs/data-model.md`](_docs/data-model.md) — the tables, how they map onto the contract, and what is still open
- [`_docs/decisions/`](_docs/decisions/README.md) — standing decisions: notes corpus, embedding model, router
- [`AGENTS.md`](AGENTS.md) — durable context and the hard rules for anyone (or anything) working here
- [`openapi.yaml`](openapi.yaml) — the API contract, written before the code
- [`_docs/ai-usage-report.md`](_docs/ai-usage-report.md) — what was delegated to agents, what a human caught

## Commands

Everything runs in containers: apart from Docker, this repository and a `.env`, nothing is installed on the host.

| Command | What it does |
| --- | --- |
| `make setup` | Create `.env` from `.env.example`, build the app image |
| `make build` | Rebuild the image after changing `db/`, `ingest/` or `tests/` |
| `make up` / `make down` | Start the stack (`db`, `ollama`) and apply migrations / stop everything |
| `make migrate` | Apply the Alembic migrations |
| `make models` | Pull the pinned embedding model into the `ollama` volume |
| `make test` / `make itest` | Unit tests (no stack) / integration tests against the running stack |
| `make lint` | Ruff over the repository |
| `make check-notes` / `make index-notes` | Validate the notes corpus against its manifest / index the changed notes |
| `make search Q="…"` | Ask the corpus a question and see the passages it would retrieve |
| `make db-port` | Also publish the database on the host, for development only |
| `make logs S=db` | Tail one service's logs |
| `make swagger` / `make swagger-stop` / `make validate-spec` | Serve, stop and lint the API contract |
