# AGENTS.md — ai-dev-prj-hermes-football

Durable context for any coding agent working in this repo (Claude Code, Codex, OpenCode, Cursor, Hermes).
Read this first. Keep it short and current: if a command, path, or rule changes, update this file in the same PR.

## What this project is

**Hermes Football** — a Telegram AI agent (the **Hermes Football gateway**; a Nous Research **Hermes Agent**
deployment is optional, see decision 0007) that answers football questions
accurately, grounded in structured data ingested daily from the free **football-data.org v4** API, plus a small
curated knowledge corpus for the qualitative parts (competition formats, tiebreakers, glossary).

Everything runs locally in **Docker Compose**. There is no VPS and no cloud host for the agent; the public
interface is the Telegram bot itself, and the dashboard is exposed through a Cloudflare tunnel.

Course context: this is the final project for the DataTalks.Club **AI Dev Tools Zoomcamp 2026**. The 12 project
criteria and how each is covered live in `_docs/scoping.md` §5 — that mapping is a deliverable, not decoration.
If you add or change a component, keep that table true. The agent team is written down in `_docs/agent-team.md`.

Status: **M1–M6 done.** The product is built end to end and the operations layer is in place. M6 added:
GitHub Actions gates plus a nightly audit; an opt-in observability stack (OTel collector -> Prometheus/Loki/Tempo ->
Grafana on loopback); one alert (`ingest_unhealthy`) evaluated by the `oncall` container against the ledger; a
read-only on-call digest; and the security artifacts (`security/capability-table.md`, a threat model, gitleaks and
dependency scans). It also fixed a real baseline defect the integration suite exposed: a knowledge search took
13-18.5 s while the MCP server waited 15 s, so the first notes question after a restart failed. The timeout budget is
now nested and asserted (40 s embedding < 45 s MCP->API < 50 s gateway). Contract v0.4.1, 19 operations. The newest
live eval run is stored red on purpose (macro-F1 0.928, retrieval 0.906, fact coverage 0.858, three answers without a
citation), and its three product misses are recorded in `_docs/follow-ups.md` rather than tuned away.

M5 added the dashboard and the scoreboard: a Next.js app over the same contract with seven routes, one admin write
(the review decision) behind `API_ADMIN_TOKEN` and a column-scoped `agent_admin` role, and `make eval`, which answers
a 48-question golden set through the shipped pipeline. M4 wired the selected router behind a binding safety gate,
measured it on a new independent 60-question holdout (gated macro-F1 0.979 on prompt v1, 0.960 on the v2 regression;
8/8 adversarial, 4/4 fabricated, 3/3 refusal and 4/4 unsupported refused), built the eight read-only MCP tools and
the Telegram gateway, reviewed thirteen notes and indexed 41 chunks. M3b selected `clef:cloud` over `tev1:0.8b`; its
cloud egress is the accepted exception for the user message, and complex answers add `beam:cloud` (decision 0007).
M2 supplies the client, bronze store, normalized pipeline, run ledger, scheduler and score-delay polling. M3 adds the
FastAPI service implementing the read operations against the contract (now v0.4.1), the freshness report, the
contract's own error semantics, and drift tests that fail on a hidden route, a reused `operationId`, a changed bound
or an undeclared enum. The retained volume and a real upstream run still need the matching local `.env` password and
a valid `UPSTREAM_API_KEY`; never put either value in the repo or a prompt. The full history and the criteria map are
in `_docs/scoping.md` §5-6.

## Architecture

```text
Telegram users
      |  long polling (no inbound ports)
      v
hermes            container: Hermes Football gateway (agent/gateway)
      |           SOUL.md (role + grounding policy); optional Nous Hermes Agent
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
                                        ollama (embeddinggemma:300m): local model, no egress
```

Supporting, all in the same Compose project: `oncall` (`agent/oncall`: alert loop + daily digest, read-only),
`observability/` (OTel collector -> Prometheus, Loki, Tempo, Grafana; opt-in profile), `security/` (capability +
threat tables, scan policy), `ops/` (runbooks, incident drills), `evals/` (golden Q&A set).

## Repo layout

```text
README.md               AGENTS.md              openapi.yaml         docker-compose.yml   Makefile
CLAUDE.md               .env.example           Dockerfile
.github/                CI, nightly scans, dependabot, PR template
_docs/                  setup-and-review.md, scoping.md, product-spec.md, rag.md, data-model.md,
                        notes-sources.md, agent-team.md, follow-ups.md, decisions/, ai-usage-report.md
db/                     SQLAlchemy models, Alembic migrations, settings, session helpers
backend/                FastAPI app (one admin write, one documented 404)
ingest/                 football-data.org client, rate limiter, loaders, scheduler, run ledger,
                        knowledge/ (corpus manifest, chunker, embedding client, indexer)
frontend/               Next.js dashboard: seven routes, one typed `server-only` API client,
                        Vitest unit tests, Playwright e2e under frontend/e2e
mcp_server/             MCP server over HTTP: eight read-only tools, backend client, name resolver
hermes/                 SOUL.md, config.yaml, agent-knowledge/*.md + manifest.yaml
agent/                  routing, hard gate, turn writer, Telegram gateway, oncall/ (alert + digest)
telemetry/              OTel setup and metric instruments; a no-op unless configured
observability/          collector, Prometheus, Loki, Tempo, Grafana provisioning and dashboards
security/               capability table, threat model, scan policy and baseline
ops/                    runbooks and incident-drill evidence
evals/                  routing holdout; evals/golden/ = questions, runner, metrics, scoreboard store
prompts/                versioned prompt bank used during development
tests/                  unit, integration (Compose stack), policy, e2e (Playwright)
```

## Stack

- Python 3.12 (FastAPI, SQLAlchemy 2.x, Alembic, httpx, APScheduler, pytest, ruff)
- Postgres 16 + pgvector; SQLite is the dev-only fallback so `DATABASE_URL` stays swappable
- Ollama for `embeddinggemma:300m` (768-d embeddings, hence `vector(768)` in Postgres). Embeddings and note text stay
  local. Routing uses `clef:cloud` (Ollama's cloud, 27B): the user message is a signed-off egress path (decision
  0003). The complex answer path sends tool results and note passages to `beam:cloud` (owner sign-off 2026-10-22,
  decision 0007); the simple path keeps them local. `tev1:0.8b` was rejected and its spike server removed.
- The Ollama *server* is a derived CPU-only build (`Dockerfile.ollama`: 637 MB against upstream's 7.05 GB), because a
  container on Apple Silicon can never load the CUDA trees upstream ships. Rebuild it with `make build`; the reasoning
  and the GPU-host escape hatch are [decision 0005](_docs/decisions/0005-ollama-image.md).
- Next.js 16 (TypeScript, strict) + a single typed API client generated from `openapi.yaml`; Vitest + Testing Library;
  Playwright for e2e. The client is `server-only`, so no token can reach the browser; pages are server-rendered and
  `force-dynamic`, because a cached dashboard would quote stale freshness.
- The M4 gateway is `agent/gateway` in the `hermes` container: Telegram long polling, one routed tool call on the
  simple path, a planner plus `beam:cloud` on the complex path, and a turn row. `hermes/SOUL.md` is the shared
  policy; `hermes/config.yaml` records the equivalent MCP surface for a future Nous Hermes Agent deployment. MCP
  tools are HTTP, not stdio.
- OpenTelemetry (SDK -> local collector -> Prometheus/Loki/Tempo -> Grafana), opt-in through
  `docker-compose.observability.yml`; the app is a no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset.
- Docker Compose for everything; GitHub Actions for CI/CD; no cloud host for the agent.

## Commands (make targets land with the scaffold — keep them working)

```bash
make setup     # create .env from .env.example, install deps
make up        # start db, ollama, backend, frontend, mcp-server, the gateway, ingest and oncall; migrate
make down      # stop everything
make test      # unit tests (fast, no network)
make itest     # integration tests against the RETAINED stack db (cleans its fixture rows)
make itest-isolated # same tests against a throwaway Compose project; use when the volume must stay untouched
make e2e       # Playwright end-to-end against the running dashboard
make frontend-test   # dashboard lint, typecheck and Vitest
make frontend-types  # regenerate the dashboard's API types from openapi.yaml
make eval      # golden-question eval run; stores the scoreboard row
make eval-self-check # prove the eval gate can fail, no model needed
make eval-backfill   # import the M4 routing artifacts as the baseline
make ci        # local parity with the pull-request gates
make ci-full   # ci + integration + browser
make security-scan   # gitleaks + pip-audit + pnpm audit
make obs-up    # opt-in observability stack, Grafana on 127.0.0.1:3001
make alert-fire      # demonstrate the alert with a synthetic stale observation
make alert-drill     # real evaluation with a 1-minute threshold
make oncall-report   # copy the digest/alert volume to data/oncall
make ingest    # trigger one ingestion run manually
make ask Q="where are Arsenal in the table?" # ask the agent through routing, MCP and the turn writer
make score-delay [MATCH_ID=…] # poll a live or recent match and report how old the provider's data is
make logs S=hermes # tail the gateway
```

## Working copy and branches (read before touching git)

- This project has **exactly one working copy**: the repository root that contains this file. Every milestone branch
  is created and checked out **there**.
- **Do not create or use `git worktree` copies** of this repo (not under a separate worktrees directory, not
  anywhere else). If a worktree for this project exists, remove the worktree directory (never the branch), then
  `git checkout` the branch at the root.
- **Work happens on a milestone branch, never directly on `main`.** `main` receives merged milestone work only. A new
  milestone starts by syncing and branching off the latest `main`, named for the milestone
  (`anammari-m3b-router-spike`, `anammari-m4-agent`, …); a milestone branch is deleted once its pull request is
  merged. Between milestones the checkout is `main`, and that is the only time being on it is expected.

```bash
# where am I? Must print the root path, one worktree line, and either a milestone branch or `main` between
# milestones.
pwd && git rev-parse --abbrev-ref HEAD && git worktree list
# get back to the shared working copy, on the latest main
cd "$(git rev-parse --show-toplevel)" && git checkout main && git pull --ff-only
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
   No write tool, no DDL, no arbitrary SQL from model output. The one write in the API is the human review decision
   (`PATCH /admin/agent-turns/{id}/review`): admin token, `agent_admin` role, UPDATE on the two review columns only, and
   a test that names it and holds it to that.
5. **No Docker socket in any container.** Isolation comes from the container boundary plus read-only mounts; do not
   add `/var/run/docker.sock` anywhere, and keep `terminal.backend` local inside the container.
6. **Secrets never enter the repo or a prompt.** `.env` is local only; `.env.example` documents keys with dummy
   values. Never log tokens, chat IDs, or full prompts with secrets.
7. **Telegram input is untrusted.** Treat every user message as a prompt-injection candidate: keep the allowlists,
   the tool schema, and the refusal behavior intact. New tool = new row in `security/capability-table.md`.
8. **Every capability is declared.** Skills, subagents, hooks, MCP tools, cron jobs and their permissions are
   written down in `_docs/permissions.md`, and every runtime capability has a row in `security/capability-table.md`.
   Undocumented capability = not shippable. `tests/test_capability_table.py` enforces the rows.
9. **Every new container is bounded.** No Docker socket, a healthcheck, a `mem_limit`/`cpus`, a line in
   `_docs/permissions.md`, and an entry in `tests/test_compose_policy.py` if it introduces a new rule.
10. **Every note is declared.** `hermes/agent-knowledge/manifest.yaml` lists every note with its source citation and
   owner; the build fails on a note missing from it or an entry with no file. The corpus is hand-written, English, one
   topic per file, reviewed like code — never generated at runtime, never scraped.
11. **Every answer says which road it took.** Each turn records whether it came from a tool or from the notes
    (`route`, `route_source`, `route_confidence`), and routing is scored in the evals. Routing is **model-first**: a
    decision model sees the user message and a fixed label set only — never retrieved text, never tool output. There is
    no regex and no deterministic pre-router. The model is `clef:cloud` (decision 0003), wired behind the binding
    safety gate in decision 0006: a non-`safe` answer refuses before a tool or note is touched, and an unreachable
    model fails closed. The same request labels the message `simple` or `complex`. Simple answers stay local; complex
    answers send the collected results to `beam:cloud`, with a citation check and a deterministic fallback (decision
    0007). No regex, no deterministic pre-router.

## Working agreement (course criteria 2-4)

- Spec before code: `_docs/product-spec.md` is the source of truth; change it in the same PR as the behavior change.
- One task per PR, small and reviewable; the task states goal + checkable acceptance criteria + out of scope.
- Prompts are versioned in `prompts/`; AI usage is logged in `_docs/ai-usage-report.md` (what was delegated,
  what was reviewed, what was rejected, what tests prove it).
- Verification is independent: whoever writes a feature does not sign it off. Prefer a test, a scan, or the
  `answer-verifier` subagent over "looks right".
- Commits: imperative subject, explain *why* in the body when it is not obvious.

## Current status / next steps

Done: repo scaffolded, scoping written (`_docs/scoping.md`), product spec for the tooling (`_docs/product-spec.md`),
the API contract reviewed and now at v0.4.1, 19 operations (`openapi.yaml`), and decision records in `_docs/decisions/` (0001 notes
corpus + manifest, 0002 embedding model, 0003 routing model comparison, 0004 the embedding tag that runs in the container). M1 is done:
schema/migration `0001_init`, the corpus with `hermes/agent-knowledge/manifest.yaml`, the chunker and embedding
client, and one note indexed/retrieved end to end in Postgres. M2 implementation adds migration `0002`, upstream
rate-limited collection, bronze payloads, scorer snapshots, the run ledger, schedule/manual entry points, and delay
polling. M2 is verified live on the retained volume: 54 unit and 9 integration tests pass, and a real run loaded
13 competitions, ~9.9k matches and standings in about 20 minutes and 162 upstream calls, ending `partial` because EC
has no standings on the free tier. A full run costs roughly 130-350 calls (about 15-30 minutes at 10 req/min); upstream
caps `/matches` at 10 days per request. M3 adds `backend/` served by `make up` on <http://localhost:8000> (`/docs`
renders the contract file): every agent-facing endpoint needs `API_AGENT_TOKEN` as a bearer token, and with no token
configured it refuses everything instead of opening up. It reads through the `agent_readonly` role. Rebuild images
(`DOCKER_BUILDKIT=0 make build`) after changing code: the containers bake it in.

Next, in order:
1. Telegram is live: the public review bot is [@review_soccer_bot](https://t.me/review_soccer_bot), and the reviewer
   steps are in [`_docs/setup-and-review.md`](_docs/setup-and-review.md). The main bot remains allowlisted. The pipeline
   is also exercised by `make ask` and the integration suite.
2. Nothing left for M2 except re-running `make score-delay` during a live match (see `_docs/scoping.md` §3). It
   reports the gap between the provider's own `lastUpdated` stamp and the moment we fetch the match — the number the
   freshness note quotes — and warns when a match has stopped being updated rather than quoting a closed record.
3. M6 is done: CI/CD, observability, the alert and on-call agent, security artifacts and the AI-usage close-out. Its
   manual verification steps are in `_docs/setup-and-review.md` and `observability/README.md`.
4. Remaining follow-ups, recorded rather than hidden in `_docs/follow-ups.md`: multi-turn conversation memory; the
   optional Nous Hermes Agent deployment described in `hermes/config.yaml`; the ingest-trigger queue that
   `POST /admin/ingest-runs` needs; the resolver misses the eval surfaced (`inter milan vs juventus`, and two clarify
   decisions on answerable questions); a dashboard login/permanent host; and a licence. The scorer tool closed
   `R-F4.1`.
