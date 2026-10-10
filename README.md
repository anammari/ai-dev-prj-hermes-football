# Hermes Football

A Telegram agent that answers football questions **accurately** — grounded in a local database refreshed daily from
football-data.org, with a read-only tool layer, an evaluation harness, and a dashboard that shows whether any of it is
actually working. Everything runs locally in Docker Compose; there is no server to rent.

Status: **scoping stage**. The specs, the API contract (v0.1.0) and the decision records exist. No application code yet.

## Milestone tracker

| M# | Item | Status |
| --- | --- | --- |
| M0 | Empty repo, scope, product spec, API contract (v0.1.0, lint clean) | Done |
| M1 | Database schema and the first migration, matching the contract: notes table with `vector(768)`, the corpus `manifest.yaml` and the local embedding provider | Next |
| M2 | Daily ingestion from football-data.org: run ledger, idempotent loads, re-indexing changed notes, measured score delay | Not started |
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
- [`_docs/decisions/`](_docs/decisions/README.md) — standing decisions: notes corpus, embedding model, router
- [`AGENTS.md`](AGENTS.md) — durable context and the hard rules for anyone (or anything) working here
- [`openapi.yaml`](openapi.yaml) — the API contract, written before the code
- [`_docs/ai-usage-report.md`](_docs/ai-usage-report.md) — what was delegated to agents, what a human caught

## Commands

Only the contract tooling exists today; the rest land with the scaffold and
[`AGENTS.md`](AGENTS.md) requires them to keep working.

| Command | What it does |
| --- | --- |
| `make setup` | Create `.env` from `.env.example`, install dependencies |
| `make up` / `make down` | Start / stop the whole Compose project |
| `make test` / `make itest` / `make e2e` | Unit, integration and end-to-end tests |
| `make eval` | Golden-question run against the agent |
| `make ingest` | Trigger one ingestion run manually |
| `make swagger` / `make validate-spec` | Serve and lint the API contract (available now) |
