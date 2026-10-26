# Product Spec — Hermes Football

Source of truth for behaviour and acceptance criteria. Sibling docs: [`scoping.md`](scoping.md) (problem and criteria
map), [`openapi.yaml`](../openapi.yaml) (API contract), [`data-model.md`](data-model.md), [`agent-team.md`](agent-team.md).

## 1. One line

A Telegram agent that answers football questions accurately from a local database refreshed daily from
football-data.org, plus a hand-written notes corpus for rules, with citations and a hard refusal when the data cannot
support an answer.

## 2. Users

| User | Need | Surface |
| --- | --- | --- |
| Football fan | Correct fixtures, results, tables, form, head-to-head, rules | Telegram bot |
| Owner | Freshness, quality, turn audit, ingestion control | Dashboard (planned) + Telegram admin |
| Reviewer | Reproduce and check the claims | Repository, tests, evals, docs |

## 3. Scope

**In:** daily ingestion, read-only API, MCP tools, Telegram agent, notes corpus + retrieval, turn log, routing gate,
dashboard, golden-question eval scoreboard, tests.

**Out:** live scores, odds, lineups, xG, predictions, betting advice, accounts/payments, Kubernetes, model training.

## 4. Compose project and egress

Everything runs in one Compose project. `hermes` long-polls Telegram (no inbound port). `mcp-server` calls only the
backend API. `backend` is the only component that reads Postgres for serving; `frontend` is the only other component
with a published port. `ingest` writes; `ollama` embeds locally; `db` stores data and vectors.

**Published ports, and only these two:** `backend` on `${BACKEND_PORT:-8000}` and `frontend` (the dashboard) on
`${FRONTEND_PORT:-3000}`. Both are for a human on this machine; the Telegram bot needs no inbound port. The dashboard
reaches the API server-side with `API_AGENT_TOKEN` and never sends that token to the browser, so a tunnel exposes
rendered pages, not credentials. A tunnel is demo-only: no permanent hostname, and it is stopped after a demo.

No service mounts the Docker socket. The corpus is read-only. `hermes` `terminal.backend` stays local inside its
container.

**Egress:** routing sends the user message to `clef:cloud` (decision 0003). The simple answer path stays local. The
complex path sends the collected tool results or note passages to `beam:cloud`; signed off for complex questions only
(decision 0007). Embeddings and note retrieval stay local. **M5 adds no new egress path:** the eval scores
deterministically (no model judge), and the verifier it validates is the same complex-path guard that was already
signed off. No other cloud call is allowed without a policy decision.

## 5. Functional requirements

### F1 — Ingestion (`ingest/`)

- Collect competitions, matches, standings, teams, squads and scorer snapshots within 10 requests/minute.
- Pace on `x-requests-available-minute` and `X-RequestCounter-Reset`; the local bucket is a safety net.
- Store bronze payloads, normalized rows, scorer snapshots and a run ledger; upserts are idempotent.
- A 403/404 on an optional sub-resource is recorded and the run continues; never fail the whole run for one.
- **AC:** a run is reproducible, rate-limit hits are visible, re-running does not duplicate rows, and the retained
  volume shows 13 competitions and ~9.9k matches from a real run.

### F2 — Database (`db/`)

- Postgres 16 + pgvector; SQLite is a dev fallback with the same code path.
- Migrations are the schema of record; `0001` schema, `0002` ingestion/scorers, `0003` turn-writer role, `0004` eval
  tables + the review role.
- Read-only `agent_readonly` role; insert-only `agent_writer` for `agent_turns`; column-scoped `agent_admin` (UPDATE on
  the two review columns only) behind the dashboard's review action; no agent DDL.
- **AC:** contract coverage test fails on a column with no contract property or a property with no home.

### F3 — Backend API (`backend/`)

- FastAPI against `openapi.yaml` v0.4.0; every agent-facing endpoint needs `API_AGENT_TOKEN`.
- No token configured means refuse everything, not open up.
- Errors use the contract's own shape (`400`, `401`, `404`, `503`); `data_as_of` on factual payloads.
- 17 operations: the 15 read operations, the two eval reads, and the one admin write the dashboard uses.
- `PATCH /admin/agent-turns/{id}/review` is the only write: `API_ADMIN_TOKEN`, the `agent_admin` role, review columns
  only. An empty admin token answers `403` (disabled), never "open".
- `POST /admin/ingest-runs` stays a documented `404` naming M6: it needs the ingest queue, because a request handler
  must not start an upstream run (rule 3).
- **AC:** contract served verbatim, response validation in tests, drift fails on a renamed field, hidden route,
  reused operationId, changed bound or undeclared enum; the review write is the only writer in `backend/` and a test
  names it and the columns it may set.

### F4 — MCP tools (`mcp_server/`)

- Eight read-only tools: standings, fixtures, match result, team form, head-to-head, top scorers, knowledge search,
  freshness.
- Compact JSON; freshness stamp included; no SQL, write path, filesystem or upstream call.
- MCP over HTTP; distinct MCP token optional; no database-owner credentials in this container.
- **AC:** each tool tested against a fake backend and the live API; an unknown argument is a protocol error, not 500.

### F5 — Agent and Telegram (`agent/gateway/`, `hermes/`)

- `SOUL.md` sets role, grounding, freshness, refusal, privacy.
- `clef:cloud` returns road, tool, safety and `simple`/`complex`.
- Simple: one tool/note, deterministic answer. Complex: planner up to four tools or eight notes, `beam:cloud`
  composition, citation + second-model claim check, deterministic fallback.
- Every turn records route, source, confidence, tool calls, model, latency, hashed chat id.
- Public review bot uses a separate token, allow-all, 5 s/user, 500 chars; main bot allowlisted.
- **AC:** database, notes, complex, override, scorer and vague questions pass integration tests; a recording failure
  withholds the answer.

### F6 — Notes and retrieval (`hermes/agent-knowledge/`)

- Hand-written English notes, one topic per file, source URL, owner, review date.
- Manifest is the inventory; missing file/entry/source fails the build.
- Chunk by headings, embed locally (`embeddinggemma:300m`, 768-d), HNSW cosine, content-hash re-index.
- Search returns passages with file/heading/score; empty is a valid "not covered" answer.
- Citations use a public GitHub URL pinned to a commit/tag.
- **AC:** 13 reviewed notes, 41 chunks; `make check-notes` and `make index-notes` pass; changing a note re-indexes it.

### F7 — Dashboard (`frontend/`)

A Next.js dashboard over the same API the agent uses: read-only except the review decision.

- `/` freshness: overall status, per-competition age and row counts, next scheduled run, recent runs with errors.
- `/standings` table explorer: competition, season, point-in-time snapshot, matchday.
- `/fixtures` fixtures and results: competition, date range, status, team, match detail.
- `/turns` agent audit log: route, route source, confidence, grounded, latency, tool calls; masked message text by
  default; the review control when admin is enabled.
- `/evals` and `/evals/{id}`: the scoreboard and one run's questions.
- `/system`: the API's own health probe.
- Every factual page shows `data_as_of` and the source (`rule 2`); a stale or unknown competition is never painted
  fresh. The browser receives no token: the client module is `server-only` and fetches server-side.
- **AC:** seven routes render from the live volume; `make frontend-test` and `make e2e` pass; a browser test proves no
  token appears in any served chunk and that the browser makes no request off the dashboard origin; the review write
  works with the admin token and is refused with the agent token.

### F8 — Scheduling

Daily ingestion, re-index changed notes, manual ingest. **AC:** schedule survives restart; failures are recorded.

### F9 — Evaluation

A 48-question golden set (`evals/golden/golden-<date>.yaml`), authored independently of the harness and audited, with
expected route, tool, notes, headings, a human rubric and machine-checkable terms. `make eval` answers every question
through the shipped pipeline and stores a run in `eval_runs`/`eval_results` plus a JSON artifact.

- Deterministic scoring only: routing per-route precision/recall/F1 and macro-F1; retrieval `recall@k` and heading
  recall; fact coverage; citation coverage; the safety gates; latency. No model judge, so no new egress and no
  judge-human agreement to report.
- A run **passes** only when macro-F1 ≥ 0.90, no false refusal, no database-question-answered-from-notes, every
  `unsupported` refusal states its reason, retrieval recall ≥ 0.90, fact coverage ≥ 0.90 and no answer lacks its
  citation. A failed run is stored and shown red with its reasons.
- The scoreboard draws one series per set (a different sample is not a trend) with the 0.90 target; the two M4 holdout
  runs are imported as `source: backfill` and report routing only, because that is all the M4 protocol measured.
- **AC:** `make eval-self-check` proves the gate bites (a perfect run passes; a run with every route wrong, no facts, or
  no citation fails); `make eval` on an unchanged set and index reproduces the routing score; the dashboard shows the
  run, its metrics and its per-question misses.

### F10 — Observability, security, reproducibility

OTel traces/metrics/logs; one actionable alert; secret scan and dependency scan; no secrets in images or logs; one
`make up` reproduces the stack. **Later.**

## 6. Non-functional

- Python 3.12, FastAPI, SQLAlchemy 2, Alembic, httpx, pytest, ruff; Next.js for dashboard.
- Local first: no VPS; Ollama for embeddings; no note text or retrieved passage in a cloud call.
- Read-only agent data path; no Docker socket; Telegram input untrusted.
- Secrets only in `.env`; never in repo, logs or prompts.

## 7. Data model sketch

`competitions`, `seasons`, `teams`, `team_competitions`, `players`, `matches`, `standings`, `top_scorers`,
`ingest_runs`, `raw_payloads`, `knowledge_chunks`, `agent_turns`, `eval_runs`, `eval_results`, `alembic_version`.
Details and open items:
[`data-model.md`](data-model.md).

## 8. Milestones

M1 schema/corpus/embedder → M2 ingestion/re-index → M3 API → M3b routing comparison → M4 agent on Telegram + notes
→ M5 dashboard + eval scoreboard (done) → M6 CI/CD, observability, alerting, on-call, security.

## 9. Success measures

1. Clean machine: `make up` gives a working bot.
2. Answerable questions ≥ 90% correct; unanswerable refused 100%.
3. Zero invented facts across two consecutive eval runs.
4. Every criterion has an artifact or an explicit gap (README table).
5. Every note has a source URL and manifest entry.
6. Routing at or above the selected target; no factual answer sourced from notes.
7. The scoreboard shows the 0.90 target, one series per golden set, and keeps a failed run visible with its reasons.
8. The dashboard shows provenance on every factual page, and no token reaches a browser.

## 10. Known limits

- Free data is delayed; scores are not live.
- No multi-turn memory; each message routes alone.
- Scorer data is served; lineups, odds, live scores and xG are not available.
- Complex answers use `beam:cloud`; the simple path is local.
- The dashboard has no login: it is local, and a tunnel is demo-only. Message text on `/turns` is masked by default.
- Golden-set scoring is deterministic, not a model judge; "completeness" means required terms present, not prose
  quality.
