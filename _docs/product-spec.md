# Product Spec — Hermes Football

Version 0.1 (scoping draft) · Scope of this version: **the tooling and system**, not the full conversational product.
Sibling documents: `_docs/scoping.md` (criteria map, architecture), `AGENTS.md` (working rules), `_docs/decisions/`
(standing decisions: the notes corpus, the embedding model, the router).

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
| `ollama` | Local model server: `embeddinggemma:300m` for the notes index, and `laya` if the M3b spike adopts model routing | none | `ollama-data` |

Only `backend` is published; the Cloudflare tunnel points at it. Telegram uses long polling, so `hermes` needs egress
only — no inbound port, no static IP, no VPS.

Rules the layout enforces:

- **No Docker socket** in any container; the knowledge corpus is mounted **read-only** into `hermes`.
- **Local inference only.** `ollama` serves the embeddings and any routing model inside the Compose network; no note
  text and no user question is sent to a hosted model provider.
- **MCP over HTTP, not stdio.** A stdio server would have to live inside the Hermes image, coupling tool code to the
  agent image and complicating its own tests and scans. As a sibling container it keeps a read-only DB role, its own
  tests and its own scan artifacts.
- **Secrets** arrive as environment variables from `.env`; never baked into an image layer, never placed in the model
  context.
- **Resource limits** live in Compose (`mem_limit`, cpus), not in Hermes `container_*` settings, which apply only to
  the Docker terminal backend we do not use.
- **Operator access** is `docker compose exec hermes hermes ...` (for example `hermes cron list`).

- **AC** `make up` on a machine with only Docker and `.env` brings all eight services up healthy, and `make down`
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

- **R-F2.1** Schema covers competitions, seasons, teams, players, matches, standings, normalized top-scorer snapshots,
  bronze raw upstream payloads, and the knowledge corpus (pgvector embeddings).
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

- **R-F6.1** `hermes/agent-knowledge/**/*.md` documents competition formats, tiebreakers, promotion/relegation, the
  API's coverage and delay policy, and a glossary — in English, one topic per file, named `<class>/<slug>.md`.
- **R-F6.1a** The corpus is **authored by hand** from stable public sources (competition regulations, the provider's
  own documentation) and reviewed like code: versioned in git, changed through pull requests, never generated at
  runtime and never scraped from a remote feed. Upstream API payloads carry no prose and are not a source.
- **R-F6.2** Files are chunked and embedded into pgvector with `embeddinggemma:300m`, served locally by the `ollama`
  container (768 dimensions, pinned in the migration as `vector(768)`); retrieval returns passages with source file and
  heading. The client applies the model's task prefixes — documents and queries are formatted differently. Each chunk
  records `embedding_model` and `embedding_dim`, so changing either is a detectable re-index rather than a silently
  mixed vector space. The tag must be runnable *by that container*: packaging that needs a macOS-only runtime is
  rejected, and the integration test probes the width the container actually returns instead of trusting the library
  page (`_docs/decisions/0002`).
- **R-F6.3** Structured questions are answered from SQL; qualitative questions from retrieval; the agent does not use
  retrieval to answer questions the database already answers correctly.
- **R-F6.4** Re-indexing a changed file is deterministic, runs on the ingest schedule (and in CI when a note changes),
  and needs no model call to decide what to index: the file's content hash says whether it is stale.
- **R-F6.5** The corpus has a compiled inventory: `hermes/agent-knowledge/manifest.yaml` lists every note's file, title,
  question classes, competitions, source citation, owner, status and review date, mirroring the file's YAML
  front-matter. A test fails when a file is missing from the manifest, when an entry has no file, or when an entry
  cites no source. Any rendered table is generated from the manifest, never hand-edited.
- **R-F6.6** Routing is explicit and recorded: a deterministic router maps the shape of the question to an intent
  bucket, a model is consulted only for ambiguous cases, and every turn stores `route`, `route_source` and
  `route_confidence`. The router sees the user message and a fixed label set only — never retrieved text, never tool
  output. Which design is used is settled by the M3b spike (`_docs/decisions/0003`), and routing accuracy is scored in
  the eval harness.
- **AC** Eval set includes both kinds; retrieval answers cite a file and heading.
- **AC** Editing a note file and re-running the indexer changes what the agent answers for the question that note covers.
- **AC** A note file without a manifest entry, or an entry without a file or a source, fails a test.
- **AC** The recorded route matches the eval harness's expected route for every golden question, and a prompt-injection
  attempt through Telegram changes neither the route nor the tool allowlist.

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
  rules/knowledge, and unanswerable (refusal expected). Each question also carries its expected route — structured
  tool or knowledge — so routing is scored on its own.
- **R-F9.2** Scoring: factual accuracy, groundedness (every claim traceable to a tool result or file),
  freshness disclosure, refusal correctness, and routing accuracy (was the right surface used). Any model-based
  judgement, such as the router spike's LLM-as-judge, is itself validated against hand-labelled cases before its
  numbers are reported.
- **R-F9.3** Runs in CI against a pinned model; results stored for trend comparison.
- **AC** A deliberately wrong answer is caught by the harness; the run produces a machine-readable report.
- **AC** A deliberately wrong route is caught by the harness as a routing failure, not as a wrong answer.

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

Eleven tables in one Alembic migration (`0001_init`), named after `openapi.yaml`. The column-by-column mapping, the
deliberate renames and the local-only tables live in `_docs/data-model.md`; this is the shape.

- `competitions` (code, name, area, type, current season with its start and end, and the coverage flags flattened into
  `coverage_fixtures`, `coverage_standings`, `coverage_scorers`, `coverage_lineups`, `coverage_live_scores`,
  `coverage_note`), `seasons` (competition, year, start, end, current flag)
- `teams` (id, name, tla, crest, area, founded, venue, club colors), `team_competitions` (which competitions a team is
  in — the table the API's `TeamDetail` needs), `players` (squad members: name, position, date of birth, nationality)
- `matches` (id, competition, season, matchday, stage, status, utc kickoff, home and away team, the score flattened
  into `score_winner`, `score_duration`, `score_full_time_*`, `score_half_time_*`, venue, referees as json, and the
  provider's own `last_updated`)
- `standings` (competition, season, snapshot date, matchday, stage, `group_label`, `table_type`, team, position, played,
  won, drawn, lost, `goals_for`, `goals_against`, `goal_difference`, points, form) — one row per team per snapshot, so
  yesterday's table stays queryable instead of being overwritten
- `ingest_runs` (id, started and finished, status, trigger, competitions, calls used, rate-limit hits,
  `rows_inserted`/`rows_updated`/`rows_unchanged`, errors as json, duration)
- `knowledge_chunks` (id, source_file, heading, ordinal, chunk_text, embedding `vector(768)`, embedding_model,
  embedding_dim, content_hash, updated_at) — derived from the hand-written English files in
  `hermes/agent-knowledge/`, which are the source of truth and are listed in its `manifest.yaml`
  (see `_docs/scoping.md` §4)
- `agent_turns` (id, `chat_id_hash`, user_message, tool_calls json, answer, grounded flag, data_as_of, model,
  latency_ms, route, route_source, route_confidence, review status and note, created_at) — the chat id is hashed and
  never stored or logged in the clear (`AGENTS.md` rule 6)

Two gaps against the contract are open and owned by M3, and are listed in `_docs/data-model.md`: v0.1.0's
`AgentTurn` carries no `route`/`route_source`/`route_confidence` although rule 10 requires them (the columns exist),
and the `KnowledgeHit.source_file` example is repo-relative while the corpus stores corpus-relative paths.

## 8. Milestones

M0 scaffold (this repo state, contract included) -> M1 database schema and the first migration, matching the contract,
including the notes table, the corpus manifest and the local embedding provider -> M2 ingestion + re-indexing of
changed notes -> M3 API -> M3b router spike (both routing designs judged against hand-checked expectations, before M4)
-> M4 agent on Telegram, with the first notes authored and reviewed -> M5 dashboard + evals -> M6 CI/CD, observability,
security, AI-usage report. Details in `_docs/scoping.md#8`; the standing decisions behind the corpus, the embedding
model and the router are recorded in `_docs/decisions/` (0001, 0002, 0003).

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
| A note exists but nobody can find it, or the corpus drifts from the plan | `manifest.yaml` is the inventory (`R-F6.5`) and a test fails when the manifest and the directory disagree |
| The router sends a factual question to the notes, or a rules question to SQL | Deterministic-first routing, the route recorded on every turn, a routing slice in the eval harness, and the M3b spike before implementation |
| An embedding model swap silently mixes vector spaces | `embedding_model` and `embedding_dim` are stored per chunk; a change forces a full re-index, which is cheap at roughly ten files |

## 10. Success measures for v1

1. `make up` on a clean machine yields a working bot that answers the golden set within threshold.
2. Eval accuracy >= 90% on answerable questions, 100% correct refusals on unanswerable ones.
3. Zero invented facts detected across two consecutive eval runs.
4. Every one of the 14 course criteria has a named, inspectable artifact (map in `_docs/scoping.md#7`).
5. Every note in `hermes/agent-knowledge/` appears in `manifest.yaml` with a source citation, and the manifest and the
   directory agree in CI.
6. Routing is correct on the golden set at or above the threshold the M3b spike sets, and no factual answer is sourced
   from the notes.
