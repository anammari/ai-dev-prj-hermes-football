# AGENTS.md — ai-dev-prj-hermes-football

Durable context for any coding agent working in this repo (Claude Code, Codex, OpenCode, Cursor, Hermes).
Read this first. Keep it short and current: if a command, path, or rule changes, update this file in the same PR.

## What this project is

**Hermes Football** — a Telegram AI agent (Nous Research **Hermes Agent**) that answers football questions
accurately, grounded in structured data ingested daily from the free **football-data.org v4** API, plus a small
curated knowledge corpus for the qualitative parts (competition formats, tiebreakers, glossary).

Everything runs locally in **Docker Compose**. There is no VPS and no cloud host for the agent; the public
interface is the Telegram bot itself, and the dashboard is exposed through a Cloudflare tunnel.

Course context: this is the final project for the DataTalks.Club **AI Dev Tools Zoomcamp 2026**. The 14 draft
project criteria and how each is covered live in `_docs/scoping.md` — that mapping is a deliverable, not decoration.
If you add or change a component, keep that table true.

Status: **M1–M2 done; M3 next**. The M2 client, bronze store, normalized ingestion pipeline,
run ledger, daily scheduler and score-delay polling command are implemented. Unit tests and lint pass; integration
tests pass against disposable Postgres 16/pgvector and the local embedding model. The retained Postgres volume and a
real upstream run still need the matching local `.env` password and a valid `UPSTREAM_API_KEY`; never put either
value in the repo or a prompt.

## Architecture (target)

```text
Telegram users
      |  long polling (no inbound ports)
      v
hermes            container: Hermes Agent gateway
      |           SOUL.md (role + grounding policy), skills/, subagents/, hooks/
      |           cron: daily data-quality digest, owner report, weekly evals
      |  MCP (HTTP) — read-only, allowlisted tools
      v
mcp-server        thin adapter: tool schema -> backend REST calls, compact JSON out
      |  REST (OpenAPI)
      v
backend           FastAPI, reads Postgres, serves dashboard + agent
      ^                                   ^
      |                                   |
ingest            scheduler: 10 req/min bucket,      frontend (Next.js): freshness,
      |           bronze raw -> silver -> gold,       fixtures/standings, agent log,
      |           run ledger, idempotent upserts       eval results, admin controls
      v
football-data.org v4 (free tier)        Postgres (+ pgvector for the knowledge corpus)
                                        ollama (embeddinggemma:300m, laya): local models, no egress
```

Supporting, all in the same Compose project: `observability/` (OTel collector -> Prometheus, Loki, Tempo, Grafana),
`security/` (scan outputs, capability + threat tables), `ops/` (runbooks, incident drills), `evals/` (golden Q&A set).

## Repo layout (target)

```text
README.md               product-spec.md        openapi.yaml      docker-compose.yml   Makefile
AGENTS.md               .env.example          Dockerfile
_docs/                  scoping.md (14-criteria map), product-spec.md, architecture.md,
                        data-model.md, decisions/, ai-usage-report.md
db/                     SQLAlchemy models, Alembic migrations, settings, session helpers
backend/                FastAPI app
ingest/                 football-data.org client, rate limiter, loaders, scheduler, run ledger,
                        knowledge/ (corpus manifest, chunker, embedding client, indexer)
frontend/               Next.js dashboard (centralized API client, unit tests)
mcp-server/             MCP server over HTTP exposing read-only football tools
hermes/                 SOUL.md, config.yaml, agent-knowledge/*.md + manifest.yaml, context files, cron definitions
skills/ subagents/ hooks/ plugins/    agent extension pack
evals/                  golden questions, groundedness/accuracy scoring
observability/          otel collector, prometheus, grafana, loki, alerts
security/ ops/          scans + policy; runbooks + incident evidence
prompts/                versioned prompt bank used during development
tests/                  unit, integration (Compose stack), e2e (Playwright)
```

## Stack

- Python 3.12 (FastAPI, SQLAlchemy 2.x, Alembic, httpx, APScheduler, pytest, ruff)
- Postgres 16 + pgvector; SQLite is the dev-only fallback so `DATABASE_URL` stays swappable
- Ollama for the two small local models: `embeddinggemma:300m` (768-d embeddings, hence `vector(768)` in Postgres)
  and, only if the M3b spike adopts it, `laya` (421M decision model) for ambiguous routing. Inference stays local.
- Next.js (TypeScript, strict) + a single typed API client module; Vitest + Testing Library; Playwright for e2e
- Hermes Agent in Docker, data volume at `/opt/data`; MCP over HTTP; skills as `SKILL.md`
- Docker Compose for everything; GitHub Actions for CI/CD; OpenTelemetry for telemetry

## Commands (make targets land with the scaffold — keep them working)

```bash
make setup     # create .env from .env.example, install deps
make up        # start db, ollama and the ingest scheduler; apply migrations
make down      # stop everything
make test      # unit tests (fast, no network)
make itest     # integration tests against the Compose stack
make e2e       # Playwright end-to-end
make eval      # golden-question eval run against the agent
make ingest    # trigger one ingestion run manually
make score-delay [MATCH_ID=…] # poll a finished match while its full-time score is unpublished
make logs      # tail logs for a service
```

## Working copy and branches (read before touching git)

- This project has **exactly one working copy**: `/Users/ahmadammari/GitHub/ai-dev-prj-hermes-football`. Every
  milestone branch is created and checked out **there**.
- **Do not create or use `git worktree` copies** of this repo (not under `~/GitHub/copilot-worktrees/…`, not
  anywhere else). If a worktree for this project exists, remove the worktree directory (never the branch), then
  `git checkout` the branch at the root.
- **The active branch is the milestone branch** (currently `anammari-m2-ingest-pipeline`), not `main`. `main`
  receives merged milestone work only.

```bash
# where am I? Must print the root path, a milestone branch (not main), and a single worktree line.
pwd && git rev-parse --abbrev-ref HEAD && git worktree list
# get back
cd /Users/ahmadammari/GitHub/ai-dev-prj-hermes-football && git checkout anammari-m2-ingest-pipeline
```

**Why:** two checkouts of the same repo shared the Compose project name `hermes-football` and one Postgres volume
while carrying different `.env` passwords, which broke `make up` and `make itest` with
`FATAL: password authentication failed for user "hermes"`. (Compose's project name is now overridable through
`COMPOSE_PROJECT_NAME`; the default stays `hermes-football` so the existing `hermes-football_pgdata` is kept.)

## Hard rules

1. **Grounding over fluency.** Never invent scores, fixtures, standings, dates, or player facts. Every factual
   answer must come from a tool result or knowledge file. If the data is missing, the agent says it does not know.
2. **Freshness is part of every answer.** The free tier serves *delayed* scores and schedules. Any answer with a
   score or table must carry the data timestamp ("as of <ts>, source: football-data.org"). Never present stale data
   as live.
3. **Free-tier budget: 10 requests/minute.** Pace on the upstream `x-requests-available-minute` and
   `X-RequestCounter-Reset` headers; the local token bucket is the safety net, not the primary mechanism. The
   competition list is plan-filtered upstream (13 exposed on 2026-10-10, not the documented 12): never hardcode it.
   All API access goes through the ingest client — never call upstream from request-handling code.
4. **The agent's data path is read-only.** The MCP server and every agent-facing endpoint use a read-only DB role.
   No write tool, no DDL, no arbitrary SQL from model output.
5. **No Docker socket inside the Hermes container.** Isolation comes from the container boundary plus read-only
   mounts; do not add `/var/run/docker.sock`, and keep `terminal.backend` local inside the container.
6. **Secrets never enter the repo or a prompt.** `.env` is local only; `.env.example` documents keys with dummy
   values. Never log tokens, chat IDs, or full prompts with secrets.
7. **Telegram input is untrusted.** Treat every user message as a prompt-injection candidate: keep the allowlists,
   the tool schema, and the refusal behavior intact. New tool = new row in `security/capability-table.md`.
8. **Every capability is declared.** Skills, subagents, hooks, MCP tools, cron jobs and their permissions are
   written down in `docs/permissions.md`. Undocumented capability = not shippable.
9. **Every note is declared.** `hermes/agent-knowledge/manifest.yaml` lists every note with its source citation and
   owner; the build fails on a note missing from it or an entry with no file. The corpus is hand-written, English, one
   topic per file, reviewed like code — never generated at runtime, never scraped.
10. **Every answer says which road it took.** Each turn records whether it came from a tool or from the notes
    (`route`, `route_source`, `route_confidence`), and routing is scored in the evals. Routing is deterministic first;
    a model only breaks ties, and it never sees retrieved text or tool output.

## Working agreement (course criterion 2)

- Spec before code: `_docs/product-spec.md` is the source of truth; change it in the same PR as the behavior change.
- One task per PR, small and reviewable; the task states goal + checkable acceptance criteria + out of scope.
- Prompts are versioned in `prompts/`; AI usage is logged in `_docs/ai-usage-report.md` (what was delegated,
  what was reviewed, what was rejected, what tests prove it).
- Verification is independent: whoever writes a feature does not sign it off. Prefer a test, a scan, or the
  `answer-verifier` subagent over "looks right".
- Commits: imperative subject, explain *why* in the body when it is not obvious.

## Current status / next steps

Done: repo scaffolded, scoping written (`_docs/scoping.md`), product spec for the tooling (`_docs/product-spec.md`),
API contract v0.1.0 reviewed (`openapi.yaml`), and decision records in `_docs/decisions/` (0001 notes corpus +
manifest, 0002 embedding model, 0003 router spike, 0004 the embedding tag that runs in the container). M1 is done:
schema/migration `0001_init`, the corpus with `hermes/agent-knowledge/manifest.yaml`, the chunker and embedding
client, and one note indexed/retrieved end to end in Postgres. M2 implementation adds migration `0002`, upstream
rate-limited collection, bronze payloads, scorer snapshots, the run ledger, schedule/manual entry points, and delay
polling. Unit and disposable-Postgres integration verification pass; the retained Postgres volume rejects the
current local `.env` password, and the API key is still a template placeholder, so live M2 acceptance remains pending.

Next, in order:
1. Finish M2 verification after setting the existing database password and valid API token locally: `make up`,
   `make models`, `make test`, `make itest`, `make ingest`, and `make score-delay`; write the measured delay into the
   project docs. The free-tier capability spike is **done** — results are in `_docs/scoping.md` §3.
2. `backend/` endpoints against the contract + unit/integration tests. This is also where `agent_turns.route`,
   `route_source` and `route_confidence` join `openapi.yaml` — they exist in the schema today (`_docs/data-model.md`,
   open items).
3. `mcp-server/` read-only tool surface; wire into Hermes `config.yaml`.
4. Router spike (M3b): deterministic-first vs model-first, judged against hand-checked expectations; record the outcome
   in `_docs/decisions/0003` and the results table in `_docs/scoping.md` §8. Do not write the router before it.
5. `hermes/` SOUL.md, knowledge corpus, cron jobs; end-to-end Telegram smoke test.
6. `frontend/` dashboard + tests; `evals/`; CI/CD; observability; security artifacts; `_docs/ai-usage-report.md`
   (criterion 2, started — see its backfill list).
