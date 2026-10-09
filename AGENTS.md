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

Status: **scoping stage**. Only `_docs/` exists. No application code yet.

## Architecture (target)

```text
Telegram users
      |  long polling (no inbound ports)
      v
hermes            container: Hermes Agent gateway
      |           SOUL.md (role + grounding policy), skills/, subagents/, hooks/
      |           cron: daily data-quality digest, owner report, weekly evals
      |  MCP (stdio) — read-only, allowlisted tools
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
```

Supporting, all in the same Compose project: `observability/` (OTel collector -> Prometheus, Loki, Tempo, Grafana),
`security/` (scan outputs, capability + threat tables), `ops/` (runbooks, incident drills), `evals/` (golden Q&A set).

## Repo layout (target)

```text
README.md               product-spec.md        openapi.yaml      docker-compose.yml   Makefile
AGENTS.md               .env.example
_docs/                  scoping.md (14-criteria map), product-spec.md, architecture.md,
                        data-model.md, decisions/, ai-usage-report.md
backend/                FastAPI app, Alembic migrations, tests/
ingest/                 football-data.org client, rate limiter, loaders, scheduler, run ledger
frontend/               Next.js dashboard (centralized API client, unit tests)
mcp-server/             MCP stdio server exposing read-only football tools
hermes/                 SOUL.md, config.yaml, agent-knowledge/*.md, context files, cron definitions
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
- Next.js (TypeScript, strict) + a single typed API client module; Vitest + Testing Library; Playwright for e2e
- Hermes Agent in Docker, data volume at `/opt/data`; MCP over stdio; skills as `SKILL.md`
- Docker Compose for everything; GitHub Actions for CI/CD; OpenTelemetry for telemetry

## Commands (make targets land with the scaffold — keep them working)

```bash
make setup     # create .env from .env.example, install deps
make up        # docker compose up -d (db, ingest, backend, mcp-server, hermes, frontend)
make down      # stop everything
make test      # unit tests (fast, no network)
make itest     # integration tests against the Compose stack
make e2e       # Playwright end-to-end
make eval      # golden-question eval run against the agent
make ingest    # trigger one ingestion run manually
make logs      # tail logs for a service
```

## Hard rules

1. **Grounding over fluency.** Never invent scores, fixtures, standings, dates, or player facts. Every factual
   answer must come from a tool result or knowledge file. If the data is missing, the agent says it does not know.
2. **Freshness is part of every answer.** The free tier serves *delayed* scores and schedules. Any answer with a
   score or table must carry the data timestamp ("as of <ts>, source: football-data.org"). Never present stale data
   as live.
3. **Free-tier budget: 10 requests/minute, 12 competitions.** All API access goes through the ingest client, which
   owns a token bucket, retries with backoff, and caches. Never call the upstream API from request-handling code.
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

## Working agreement (course criterion 2)

- Spec before code: `_docs/product-spec.md` is the source of truth; change it in the same PR as the behavior change.
- One task per PR, small and reviewable; the task states goal + checkable acceptance criteria + out of scope.
- Prompts are versioned in `prompts/`; AI usage is logged in `_docs/ai-usage-report.md` (what was delegated,
  what was reviewed, what was rejected, what tests prove it).
- Verification is independent: whoever writes a feature does not sign it off. Prefer a test, a scan, or the
  `answer-verifier` subagent over "looks right".
- Commits: imperative subject, explain *why* in the body when it is not obvious.

## Current status / next steps

Done: repo scaffolded, scoping written (`_docs/scoping.md`), product spec for the tooling (`_docs/product-spec.md`).

Next, in order:
1. `openapi.yaml` + DB schema and Alembic migration (contract first).
2. `ingest/` client with the rate limiter and run ledger; spike which sub-resources the free tier really returns.
3. `backend/` endpoints against the contract + unit/integration tests.
4. `mcp-server/` read-only tool surface; wire into Hermes `config.yaml`.
5. `hermes/` SOUL.md, knowledge corpus, cron jobs; end-to-end Telegram smoke test.
6. `frontend/` dashboard + tests; `evals/`; CI/CD; observability; security artifacts.
