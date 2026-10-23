# Hermes Football

A Telegram agent that answers football questions accurately. Facts come from a local Postgres database refreshed
daily from the free football-data.org API; rules and definitions come from a small hand-written notes corpus. Every
answer says how old the data is and cites its source. When the data cannot support an answer, the bot says so.

Status: **built through the Telegram agent; dashboard and operations next.** The routing gate is measured on an
independent holdout, the MCP tools and Telegram gateway work end to end, and the notes corpus is indexed. The public
review bot is [@review_soccer_bot](https://t.me/review_soccer_bot) (`reviewsoccerbot`).

Try it: open the bot, send `/start`, then ask:
- `where are Arsenal in the table?` — a database answer with a timestamp.
- `how does the championship playoff work?` — a notes answer with a public link.
- `Compare Arsenal's league position with their recent form and say whether they are in the title race.` — a
  complex answer that combines two tools.

Local reviewer runbook: [`_docs/setup-and-review.md`](_docs/setup-and-review.md#local-test-runbook).

## Repository map

```text
.
├── README.md, AGENTS.md, CLAUDE.md        entry point, agent rules, operational rules
├── openapi.yaml                          API contract, v0.3.0
├── docker-compose.yml, Dockerfile, Makefile
├── _docs/
│   ├── setup-and-review.md               launch, test, review, troubleshooting
│   ├── scoping.md                        problem, data limits, criteria map, plan
│   ├── product-spec.md                   requirements and acceptance criteria
│   ├── rag.md                            notes corpus, retrieval and evaluation
│   ├── data-model.md                     tables and open data-model items
│   ├── notes-sources.md                  public source URL per note
│   ├── agent-team.md                     roles and hand-offs
│   ├── ai-usage-report.md                delegated, reviewed, rejected, evidence
│   └── decisions/                        one-page records 0001–0007
├── backend/                              FastAPI read-only API over Postgres
├── db/                                   SQLAlchemy models, Alembic migrations
├── ingest/                               football-data.org client, loaders, scheduler, knowledge index
├── mcp_server/                           eight read-only MCP tools over HTTP
├── agent/                                router, hard safety gate, planner/composer, turn writer, Telegram gateway
├── hermes/                               SOUL.md, config.yaml, notes and manifest
├── prompts/                              versioned prompt bank
├── evals/routing/                        routing holdout and results
└── tests/                                unit and integration tests
```

`frontend/` (dashboard), `observability/`, `security/` and `ops/` are planned, not present yet.

## How the 12 criteria are covered

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Problem description | Met | [`_docs/scoping.md`](_docs/scoping.md) §1–3 |
| 2 | Product specification | Partly | [`_docs/product-spec.md`](_docs/product-spec.md), [`openapi.yaml`](openapi.yaml), [`_docs/scoping.md`](_docs/scoping.md) §8. Gap: no public task tracker |
| 3 | Agent team | Met | [`_docs/agent-team.md`](_docs/agent-team.md), [`prompts/`](prompts/README.md), [`_docs/ai-usage-report.md`](_docs/ai-usage-report.md) |
| 4 | Context management | Met | [`AGENTS.md`](AGENTS.md), [`_docs/`](_docs), decisions |
| 5 | Application | Open | Backend, MCP tools, agent and ingestion work; dashboard missing. Start at [`backend/`](backend), [`agent/gateway/`](agent/gateway), [`mcp_server/`](mcp_server) |
| 6 | Testing | Partly | `make test` **358 passed**, `make itest` **38 passed**, lint clean. No e2e until the dashboard exists |
| 7 | Containerization | Partly | `make up` starts six services with health checks; dashboard missing. [`docker-compose.yml`](docker-compose.yml) |
| 8 | Deployment | Partly | Telegram long polling; dashboard tunnel planned, no public deployment yet |
| 9 | CI/CD | Open | Local gates only; workflows are next |
| 10 | Observability | Open | OTel stack planned |
| 11 | Alerting | Open | Staleness/failure alert planned |
| 12 | On-call agent | Open | Cron digests and verifier planned |

The detailed map with gaps is [`_docs/scoping.md`](_docs/scoping.md#5-how-the-12-course-criteria-are-covered).

## The agent in one minute

1. `clef:cloud` reads the message and labels the road (`tool`, `knowledge`, `clarify`, `refuse`), the tool, safety,
   and `simple` or `complex`.
2. Any safety label other than `safe` refuses before a tool or note is touched.
3. Simple: one tool or one note retrieval, deterministic answer.
4. Complex: planner chooses up to four tools, or retrieves eight notes, and `beam:cloud` composes with a citation
   check and a deterministic fallback.
5. The turn is written to `agent_turns` through an insert-only role, then sent.

Only the user message goes to `clef:cloud`. Simple answers stay local; complex answers send the collected results to
`beam:cloud`. Embeddings and note retrieval stay local.

## Run it

Prerequisite: Docker, repository, `.env` (`make setup` once).

```bash
make up
make ask Q="how does the championship playoff work?"
make test
make lint
make itest
make check-notes
make down
```

One `make up` starts `db`, `ollama`, `backend`, `mcp-server`, `hermes` and `ingest`. Only `backend` publishes port
`8000`. Review bot setup and the Telegram test steps are in
[`_docs/setup-and-review.md`](_docs/setup-and-review.md).

## Documents

- [`_docs/setup-and-review.md`](_docs/setup-and-review.md) — launch, reviewer test, owner Telegram setup
- [`_docs/scoping.md`](_docs/scoping.md) — problem, data limits, criteria map, plan
- [`_docs/product-spec.md`](_docs/product-spec.md) — requirements, acceptance criteria, milestones
- [`_docs/rag.md`](_docs/rag.md) — notes, chunking, embeddings, retrieval
- [`_docs/data-model.md`](_docs/data-model.md) — tables and open items
- [`_docs/notes-sources.md`](_docs/notes-sources.md) — source URLs for every note
- [`_docs/agent-team.md`](_docs/agent-team.md) — roles and process
- [`_docs/ai-usage-report.md`](_docs/ai-usage-report.md) — what agents did, what humans caught
- [`_docs/decisions/`](_docs/decisions/README.md) — decisions not to re-litigate
- [`evals/routing/results/`](evals/routing/results/) — routing evidence

## Limits, stated

- Dashboard, golden-question scoreboard, CI/CD, observability and security artifacts are M5/M6.
- No multi-turn memory; each message routes on its own.
- Top-scorer data is served; lineups, odds, live scores and xG are not available on the free tier.
- The free provider is delayed; never presented as live.
