# Hermes Football

A Telegram bot that answers football questions **accurately** — from a local database refreshed every day from
football-data.org, plus a small hand-written set of notes about the rules, which the bot searches rather than guesses
from ([how that works, and how it is scored](_docs/rag.md)). When the data does not support an answer, it says so
instead of guessing. Everything runs on your own machine in Docker; there is no server to rent.

Status: **M1–M3b done; M4 next.** The routing comparison chose `clef:cloud` and the owner signed it off on
2026-10-20, with its cloud egress accepted. Selection is not production wiring: the model's refusal gap is an M4
safety gate. The backend, database and ingestion work; the Telegram agent, dashboard and production pipeline are M4-M6.

## How to read this README

One short section per course criterion, using the current names from the
[course project brief](https://github.com/anammari/ai-dev-tools-zoomcamp/tree/main/project). Each starts with its
status: **Met**, **Partly**, or **Open**. The evidence-and-gap table is
[`_docs/scoping.md` §7](_docs/scoping.md#7-how-the-12-course-criteria-are-covered).

## 1. Problem Description

**Met.** Football answers are easy to find and often wrong: scores arrive late, tables go stale, and a confident
model will invent both. This bot answers fixtures, results, standings and competition rules from the free
football-data.org API plus a small hand-written corpus, and puts the data's own timestamp on every answer. When the
data cannot support an answer — a missing competition, an unplayed match, a rule nobody wrote down — it says so.
Predictions, betting tips and live scores are out of scope on purpose. The full problem statement is in
[`_docs/scoping.md`](_docs/scoping.md) and [`_docs/product-spec.md`](_docs/product-spec.md).

## 2. Product Specification

**Partly.** [`_docs/product-spec.md`](_docs/product-spec.md) is the source of truth, [`openapi.yaml`](openapi.yaml)
(v0.2.0) is the API contract, and [`_docs/scoping.md`](_docs/scoping.md) §8 is the milestone plan with acceptance
criteria. The gap is a **public task tracker**: the course wants tasks with acceptance criteria and evidence that
the agents used the tracker. The milestone plan and pull-request record are not a tracker; moving the plan to
GitHub Issues is on the M6 list.

## 3. Agent Team Specification

**Met.** [`_docs/agent-team.md`](_docs/agent-team.md) defines the owner, the coding agent, the independent
reviewers, the planned verifier, and the hand-off process: plan before code, one milestone branch, evidence not
confidence, decisions recorded, the human signs policy changes. [`prompts/`](prompts/README.md) and
[`_docs/ai-usage-report.md`](_docs/ai-usage-report.md) make the process inspectable.

## 4. Context Management

**Met.** [`AGENTS.md`](AGENTS.md) is the entry point and links the modular docs: scope, product spec, data model,
agent team, decisions, RAG notes, API contract, AI-usage report and the routing comparison. It stays short enough to
read first, and a change to a hard rule lands in the same pull request as the behaviour.

## 5. Application

**Open.** The backend, Postgres and ingestion work end to end: 14 read-only operations served from the database, the
OpenAPI contract served verbatim, freshness on every factual answer, and a daily collector. The dashboard and the
Telegram/Hermes agent do not exist yet, so this is not the full-stack application the criterion asks for. Backend:
[`backend/`](backend); database: [`db/`](db), [`_docs/data-model.md`](_docs/data-model.md); collection:
[`ingest/`](ingest).

## 6. Testing

**Partly.** Unit tests and integration tests exist and pass:
`make test` (256 unit tests, no network) and `make itest` (the real Compose stack, from collection to the API). The
gap is one command for both: the course asks for unit **and** integration tests with a single command, and these
are deliberately separate so the fast suite stays fast. Contract drift is covered by
[`tests/test_api_contract.py`](tests/test_api_contract.py), which fails on a renamed field, a hidden route, a reused
`operationId`, a changed bound or an undeclared enum value.

## 7. Containerization

**Partly.** One `make up` starts `db`, `ollama`, `backend` and the ingest scheduler, with health checks and one
published port; `make down` leaves no orphans. The gap is that the dashboard and Hermes are not in the Compose
project yet, so "the full system" is not one command — [`docker-compose.yml`](docker-compose.yml),
[`Makefile`](Makefile).

## 8. Deployment

**Partly.** The deployment is demo-scoped: the Telegram bot uses long polling (no inbound port) and the dashboard
is exposed through a temporary Cloudflare tunnel for the recorded demo, then stopped ([`_docs/scoping.md`](_docs/scoping.md)
§6). The steps are written down; no working public deployment is shown yet, so this is not the "reachable at a
public URL" level.

## 9. CI/CD

**Open.** No workflows yet. The local gates are `make test` and `make lint`; pull requests do not run them
automatically and there is no deploy or rollback path. `.github/workflows/` and the rollback drill are M6.

## 10. Observability

**Open.** No telemetry yet. The plan is OpenTelemetry from backend and ingest to a collector, Prometheus/Loki/Tempo,
and a Grafana view keyed by the request id the API already returns; nothing is instrumented today.

## 11. Alerting on User Impact

**Open.** No alert yet. The planned alert is data staleness or repeated agent failures, with the impact in the
payload; it lands with M6 and the observability stack.

## 12. On-Call Agent

**Open.** No agent wakes on an alert yet. Hermes cron jobs (daily digest, owner report, weekly evals) and the
`answer-verifier` subagent are M4/M6; until then a human is on call.

## Supporting work (not a separate criterion)

- **Routing comparison:** two decision models routed the same 85 hand-labelled questions through the same request;
  `clef:cloud` beat `tev1:0.8b` — 71% v 53% accuracy, macro-F1 0.70 v 0.43. clef was selected, its cloud egress is
  signed off, and its 3/5 refusal gap is the M4 safety gate. [Result report](evals/routing/results/2026-10-19T12-40-46Z.md).
- **API contract:** `openapi.yaml` is written before the backend, served verbatim at `/openapi.yaml`, and a test
  fails when the two drift apart. Every agent-facing endpoint needs `API_AGENT_TOKEN`; with no token configured it
  refuses everything.
- **Data discipline:** the collector paces on the provider's own headers (10 requests/minute), stores bronze
  payloads, upserts idempotently and writes a run ledger. The retained volume holds 13 competitions, ~9.9k matches
  and standings from a real run.
- **Security:** the agent's data path is read-only; no Docker socket; the corpus is mounted read-only; secrets stay
  in `.env`; Telegram input is treated as untrusted. The capability and threat tables are M6 artifacts.
- **Reproducibility:** `make setup`, `make up`, `make test` and `make itest` are the entry points; the working-copy
  and branch rules are in [`AGENTS.md`](AGENTS.md).

## Milestone tracker

| M# | Item | Stage |
| --- | --- | --- |
| M0 | Empty repo, scope, product spec, API contract | Done |
| M1 | Database schema and first migration, notes table with vectors, corpus manifest and local embedding | Done |
| M2 | Daily collection from football-data.org: run ledger, idempotent loads, re-indexing changed notes | Done |
| M3 | Backend API against `openapi.yaml`: fourteen read-only operations, read-only role, freshness report, drift test | Done |
| M3b | Routing comparison: `tev1:0.8b` (local) vs `clef:cloud`, scored on precision/recall; clef selected | Done |
| M4 | Telegram agent: `SOUL.md`, first notes reviewed, clef routing wired behind the safety gate, refusal and freshness behaviour | **Next** |
| M5 | Dashboard and eval scoreboard, including routing precision/recall over time | Later |
| M6 | CI/CD, observability, alerting, on-call agent, security artifacts and the AI-usage report close-out | Later |

Each milestone's meaning and "done when" are in [`_docs/scoping.md`](_docs/scoping.md) §8. The current gaps against
the 12 criteria are in [`_docs/scoping.md`](_docs/scoping.md) §7.

## Project documents

- [`_docs/scoping.md`](_docs/scoping.md) — start here: what we are building, what the free API allows, how the 12
  criteria are covered, and the milestone plan
- [`_docs/product-spec.md`](_docs/product-spec.md) — requirements, acceptance criteria, data model
- [`_docs/agent-team.md`](_docs/agent-team.md) — the agent roles and the hand-off process
- [`_docs/data-model.md`](_docs/data-model.md) — the tables, how they map onto the contract, and what is still open
- [`_docs/rag.md`](_docs/rag.md) — the notes the bot can search: chunking, embedding, storage and scoring
- [`openapi.yaml`](openapi.yaml) — the API contract, written before the code
- [`_docs/decisions/`](_docs/decisions/README.md) — standing decisions: notes corpus, embedding model, routing model
- [`_docs/ai-usage-report.md`](_docs/ai-usage-report.md) — what was delegated to agents, and what a human caught
- [`prompts/`](prompts/README.md) — the versioned prompt bank
- [`evals/routing/results/`](evals/routing/results/) — the routing comparison's evidence

## Commands

```bash
make setup     # create .env from .env.example and build the app image
make up        # start db, ollama, the backend API and the ingest scheduler; apply migrations
make down      # stop everything, keep the volumes
make test      # unit tests (fast, no network)
make itest     # integration tests against the retained stack
make itest-isolated # same tests against a throwaway Compose project
make lint      # ruff over the repository
make ingest    # trigger one ingestion run manually
make score-delay [MATCH_ID=…] # measure the provider's data age for a live or recent match
make logs S=db # tail one service
```

`make e2e` and `make eval` arrive with the dashboard and the eval harness (M5). On a machine where buildx cannot
write its state directory, prefix a build with `DOCKER_BUILDKIT=0`.
