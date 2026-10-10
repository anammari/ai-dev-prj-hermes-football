# Product Spec — Hermes Football

Version 0.1 (scoping draft) · Scope of this version: **the tooling and system**, not the full conversational product.
Sibling documents: `_docs/scoping.md` (criteria map, architecture), `AGENTS.md` (working rules).

## 1. One-liner

A Telegram agent that answers football questions **accurately**, grounded in a local database refreshed daily from
football-data.org, with an auditable tool layer, an evaluation harness, and a dashboard that shows whether any of it
is actually working.

## 2. Users

| User | Need | Surface |
| --- | --- | --- |
| Football fan (end user) | Correct, current-enough answers in plain language: fixtures, results, standings, form, head-to-head, competition rules | Telegram chat with the Hermes bot |
| Owner / admin (project author) | See data freshness, judge agent quality, inspect what the agent did, control ingestion | Dashboard + Telegram admin commands |
| Reviewer / peer evaluator | Reproduce the system and check the claims: tests, scans, evals, AI-usage report | Repo + README + `_docs/` |
| Future contributor agent (Claude Code, Codex, Hermes) | Enough durable context to change the system without breaking the rules | `AGENTS.md`, `_docs/`, tests |

## 3. In scope / out of scope

**In scope (v1 tooling)**

- Scheduled ingestion from football-data.org free tier into a local database.
- Read-only REST API + OpenAPI contract for every fact the agent may state.
- MCP tool server exposing a narrow, typed tool surface to Hermes.
- Hermes agent: grounded answering, refusal behavior, freshness stamping, admin/user separation.
- Knowledge corpus + retrieval for qualitative football questions.
- Dashboard: freshness, explorer, agent log, eval results, admin actions.
- Eval harness with a golden question set and CI thresholds.
- Tests (unit, integration, e2e), CI/CD, observability with one actionable alert, security artifacts.

**Out of scope for v1**

- Live (in-play) scores, odds, lineups, xG or any paid-tier data point.
- Match prediction, betting advice, or any claim the data cannot support.
- Accounts, payments, multi-tenant hosting, mobile apps.
- Kubernetes or a VPS deployment; production-scale traffic.
- Training or fine-tuning models.

## 4. The Compose project

Everything runs locally in one Compose project. Nothing is installed on the host except Docker, this repository and a
`.env`. Three different things get called "container" here, and the distinction matters:

| Layer | What it is | This project |
| --- | --- | --- |
| Hermes itself | The agent process: gateway, Telegram adapter, cron scheduler | A container, data volume at `/opt/data` |
| Hermes tool backend (`terminal.backend`) | Where the agent's shell commands run: `local`, `docker`, `ssh`, `modal`… | `local` — inside Hermes' own container, which is the boundary |
| Our application | backend, ingest, mcp-server, Postgres, frontend, observability | One container each |

We deliberately do **not** use `terminal.backend: docker`: it would require mounting the Docker socket into the
agent's container, which is root-equivalent control of the host. The container is the isolation boundary.

| Service | Role | Host port | Volume |
| --- | --- | --- | --- |
| `hermes` | Gateway, Telegram long polling, cron, skills, `SOUL.md` | none | `hermes-data` → `/opt/data` |
| `mcp-server` | Read-only football tools over HTTP on the Compose network | none | — |
| `backend` | FastAPI: the only component that reads Postgres, and the only one serving the contract | 8000 | — |
| `ingest` | Scheduler, upstream client, run ledger | none | — |
| `db` | Postgres 16 + pgvector | none (5432 exposed in dev only) | `pgdata` |
| `frontend` | Next.js dashboard | 3000 (dev) | — |
| `obs` | OTel collector, Prometheus, Loki, Tempo, Grafana | 3001 | `grafana-data` |

Only `backend` is published; the Cloudflare tunnel points at it. Telegram uses long polling, so `hermes` needs egress
only — no inbound port, no static IP, no VPS.

Rules the layout enforces:

- **No Docker socket** in any container; the knowledge corpus is mounted **read-only** into `hermes`.
- **MCP over HTTP, not stdio.** A stdio server would have to live inside the Hermes image, coupling tool code to the
  agent image and complicating its own tests and scans. As a sibling container it keeps a read-only DB role, its own
  tests and its own scan artifacts.
- **Secrets** arrive as environment variables from `.env`; never baked into an image layer, never placed in the model
  context.
- **Resource limits** live in Compose (`mem_limit`, cpus), not in Hermes `container_*` settings, which apply only to
  the Docker terminal backend we do not use.
- **Operator access** is `docker compose exec hermes hermes ...` (for example `hermes cron list`).

- **AC** `make up` on a machine with only Docker and `.env` brings all seven services up healthy, and `make down`
  leaves no orphan containers.
- **AC** No service other than `backend` publishes a host port, and `docker inspect` shows no Docker socket mount
  anywhere.

## 5. Functional requirements and acceptance criteria

Acceptance criteria are **checkable**: a reviewer should be able to answer yes/no without interpretation.

### F1 — Ingestion pipeline (`ingest/`)

- **R-F1.1** A daily scheduled run loads, for every competition the plan exposes (13 observed on 2026-10-10, not a
  hardcoded 12): the competition record, teams and squads, matches (season fixtures + results), standings and top
  scorers. Fixtures and results are fetched **in batch across competitions by date window**, not competition by
  competition.
- **R-F1.2** All upstream traffic passes through one client that paces on the upstream `x-requests-available-minute`
  and `X-RequestCounter-Reset` headers and enforces **<= 10 requests/minute** as a hard ceiling, with backoff on
  429/5xx, a retry ceiling, and upstream 403 treated as `data_not_available`.
- **R-F1.3** Runs are **idempotent**: re-running the same day does not duplicate rows.
- **R-F1.4** Raw payloads are stored (bronze) and normalized into serving tables (silver).
- **R-F1.5** Each run writes a ledger row: start/end, status, upstream calls used, rows upserted, errors.
- **AC** `make ingest` twice in a row -> second run reports 0 inserted / N unchanged, ledger shows both runs, and no
  API call exceeds the rate limit (asserted in a unit test with a fake clock).

### F2 — Database (`db/`, Postgres + Alembic)

- **R-F2.1** Schema covers competitions, seasons, teams, players, matches, standings, and the knowledge corpus
  (pgvector embeddings).
- **R-F2.2** All schema changes are Alembic migrations; `alembic upgrade head` is part of container start.
- **R-F2.3** The same code path runs on SQLite (dev) and Postgres (compose) via `DATABASE_URL`.
- **R-F2.4** The agent-facing role is **read-only**.
- **AC** Fresh clone -> `make up` migrates an empty database and `/meta/freshness` returns 200; a write attempt with
  the agent role fails.

### F3 — Backend API (`backend/`, FastAPI)

- **R-F3.1** `openapi.yaml` is written before the code and describes every endpoint the frontend or agent uses.
- **R-F3.2** Endpoints: `/health`, `/meta/freshness`, `/competitions`, `/competitions/{code}/standings`,
  `/competitions/{code}/matches`, `/teams/{id}`, `/teams/{id}/form`, `/matches/{id}`, `/search/knowledge`.
- **R-F3.3** Every factual response carries `source` and `data_as_of` (upstream data timestamp), never just "now".
- **R-F3.4** Responses are bounded (limit/pagination) and typed; errors use a documented error shape.
- **AC** A contract test fails if a route's request/response shape drifts from `openapi.yaml`; integration tests hit
  the running stack, not a mock.

### F4 — MCP tool server (`mcp-server/`)

- **R-F4.1** Exposes read-only tools: `get_standings`, `get_fixtures`, `get_match_result`, `get_team_form`,
  `get_head_to_head`, `search_knowledge`, `get_data_freshness`.
- **R-F4.2** Tool outputs are compact and LLM-sized (top-N rows, no raw dumps) and always include the freshness stamp.
- **R-F4.3** No arbitrary SQL, no write path, no filesystem access; per-call timeout and input validation.
- **AC** Each tool has a unit test and one recorded example call; a prompt-injection test shows that no user text can
  cause a non-allowlisted tool call or a wider query.

### F5 — Hermes agent and Telegram (`hermes/`)

- **R-F5.1** `SOUL.md` defines role, tone, and the grounding policy: answer only from tool results or knowledge files;
  say "I don't know" otherwise; never present delayed data as live.
- **R-F5.2** The agent discloses the data timestamp whenever it states a score, fixture or table.
- **R-F5.3** Admin and public users are separated (`allow_admin_from`); admin commands are allowlisted.
- **R-F5.4** Conversations are logged locally for review, with a retention rule.
- **R-F5.5** Hermes runs as a container in the same Compose project; no Docker socket is mounted.
- **AC** A Telegram smoke test passes the scripted question set; unanswerable questions produce a refusal, not a guess.

### F6 — Knowledge corpus and retrieval

- **R-F6.1** `hermes/agent-knowledge/*.md` documents competition formats, tiebreakers, promotion/relegation, the API's
  coverage and delay policy, and a glossary.
- **R-F6.2** Files are chunked and embedded into pgvector; retrieval returns passages with source file and heading.
- **R-F6.3** Structured questions are answered from SQL; qualitative questions from retrieval; the agent does not use
  retrieval to answer questions the database already answers correctly.
- **AC** Eval set includes both kinds; retrieval answers cite a file and heading.

### F7 — Dashboard (`frontend/`)

- **R-F7.1** Views: data freshness + ingestion runs, competitions/standings/fixtures explorer, agent conversation log
  with review flags, eval results over time.
- **R-F7.2** One typed API client module; no scattered `fetch` calls.
- **R-F7.3** Unit tests on core logic and components, with run instructions; Playwright covers the two key flows
  (open dashboard -> see freshness; ask the agent -> see the logged answer).
- **AC** `make test` and `make e2e` pass from a clean checkout.

### F8 — Scheduling and automation

- **R-F8.1** Daily ingestion job (container scheduler) at a fixed local time, with a manual trigger.
- **R-F8.2** Hermes cron jobs: a daily data-quality digest delivered to the admin (deterministic script output first,
  LLM summarization second) and a weekly eval run.
- **R-F8.3** Failed or stale ingestion raises an alert; the alert payload carries service, environment, version, and
  the impact ("data older than N hours").
- **AC** Kill the ingestion job mid-run -> alert fires within the configured window; ledger shows the failed run.

### F9 — Evaluation harness (`evals/`)

- **R-F9.1** 30-50 golden questions with expected facts, grouped: fixtures, results, standings, form, head-to-head,
  rules/knowledge, and unanswerable (refusal expected).
- **R-F9.2** Scoring: factual accuracy, groundedness (every claim traceable to a tool result or file),
  freshness disclosure, refusal correctness.
- **R-F9.3** Runs in CI against a pinned model; results stored for trend comparison.
- **AC** A deliberately wrong answer is caught by the harness; the run produces a machine-readable report.

### F10 — Observability, security, and reproducibility

- **R-F10.1** OTel instrumentation on backend and ingest -> collector -> Prometheus/Loki/Tempo/Grafana.
- **R-F10.2** One actionable alert tied to user impact (data staleness / repeated agent failures).
- **R-F10.3** `security/capability-table.md` lists every agent capability, credential, and data access, with a threat
  model for the MCP server and the untrusted Telegram input path.
- **R-F10.4** Deterministic scans (Semgrep, dependency and image scan), an agent-supply-chain scan, and PR audit
  output are committed under `security/` and `docs/`.
- **R-F10.5** `_docs/ai-tool-policy.md` states which model providers see which data, retention, and approval rules.
- **AC** `make setup && make up && make e2e` works from a clean clone on a machine that has only Docker and an API key.

## 6. Non-functional requirements

| Area | Target |
| --- | --- |
| Correctness | No invented fact in the eval set; every factual answer carries source + timestamp |
| Data freshness | Fixtures/standings refreshed daily; freshness surfaced in the dashboard and in answers |
| Upstream budget | <= 10 req/min, <= ~1,500 calls/day, cached responses reused across competitions |
| Latency | Agent replies within ~10 s p95 for tool-backed answers; dashboard loads < 2 s locally |
| Cost | Free tier API + the model provider in use; ingestion and tool calls must not require paid data |
| Portability | Compose is the single entry point; SQLite/PgSQL switch stays working |
| Auditability | Every ingestion run, tool call, answer, and admin action is logged or reconstructable |

## 7. Data model sketch

- `competitions` (code, name, area, tier_fee), `seasons` (competition, start/end, current flag)
- `teams` (id, name, tla, crest, area), `players` (optional, only if free tier returns squads)
- `matches` (id, competition, season, matchday, utc kickoff, status, home/away team, score, last_updated)
- `standings` (competition, season, snapshot date, team, position, played, won, drawn, lost, gf, ga, points, form)
- `ingest_runs` (id, started_at, finished_at, status, calls_used, rows_upserted, errors)
- `knowledge_chunks` (id, source_file, heading, chunk_text, embedding vector, updated_at)
- `agent_turns` (id, chat_id, user_message, tool_calls json, answer, grounded flag, data_as_of, created_at)

## 8. Milestones

M0 scaffold (this repo state) -> M1 contract + schema -> M2 ingestion -> M3 API -> M4 agent on Telegram ->
M5 dashboard + evals -> M6 CI/CD, observability, security, AI-usage report. Details in `_docs/scoping.md#8`.

## 9. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Free-tier capabilities drift (a resource moves to a paid tier, the plan-filtered competition list changes) | The verified set is recorded in `_docs/scoping.md` §3; a re-runnable probe in CI reports a change instead of failing at answer time |
| The score delay is unmeasured, so "delayed" could be mistaken for "live" | M2 measures it by polling one finished match until its score appears; the freshness stamp then carries the measured number |
| Delayed data mistaken for live data | Freshness stamping enforced in the API layer, not only in the prompt |
| Agent hallucinating scores under pressure | Grounding policy in `SOUL.md` + eval cases with unanswerable questions + retrieval of facts only via tools |
| Rate limit exhaustion from retries or dev usage | Token bucket, cache table for repeated windows, dev environment reads from the local DB only |
| Scope creep (prediction, betting, live scores) | Explicit non-goals in §3; new features must name the criterion or user need they serve |
| Prompt injection through Telegram | Read-only tool surface, allowlists, injection test suite, no secrets in context |

## 10. Success measures for v1

1. `make up` on a clean machine yields a working bot that answers the golden set within threshold.
2. Eval accuracy >= 90% on answerable questions, 100% correct refusals on unanswerable ones.
3. Zero invented facts detected across two consecutive eval runs.
4. Every one of the 14 course criteria has a named, inspectable artifact (map in `_docs/scoping.md#7`).
