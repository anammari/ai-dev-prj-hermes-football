# Scoping — Hermes Football (ai-dev-prj-hermes-football)

Status: **draft, scoping stage**. This file is the project's map: what we build, why each piece exists, and how each
of the 14 course project criteria is covered. Update it when scope changes — a criteria row that no longer matches
reality is a bug in the deliverable.

---

## 1. Original brief

- A **Hermes AI agent** that answers football questions accurately on **Telegram**.
- Data source: a free-tier football API — **football-data.org**.
- Hermes, its backend and the Telegram hook all run in **Docker**.
- A **scheduled workflow** ingests batch data from the API daily into the backend store.
- An **API wraps the database** so the agent can use tool calling to fetch the right rows for the LLM.
- Inspired by the tutorial project `MariyaSha/hermes_business_agent` (RAG over a company-specific text corpus).
- Constraints: **localhost only** — no VPS hosting for Hermes.

## 2. Reference project anatomy (what we learned from it)

`hermes_business_agent` is five files; the value is in the pattern, not the code:

| Piece | Role |
| --- | --- |
| `agent-knowledge/*.md` (5 files) | Grounding corpus, mounted at `/opt/data/agent-knowledge/`, read by the agent directly |
| `SOUL.md` | Role + personality **and the refusal/grounding policy**: files are the source of truth, never invent prices or policies, say "I don't know" |
| `scripts/daily_report.py` | Deterministic Python: reads Hermes' own SQLite `state.db`, counts sessions and messages, prints a compact payload — no LLM involved |
| `DAILY_PROMPT.md` | Prompt that turns that payload into an owner report, run by a Hermes **cron** job |
| `README.md` | VPS deploy, Telegram gateway, `allow_admin_from`, `user_allowed_commands`, cron |

Two ideas we adopt deliberately:

1. **Deterministic code does the counting; the LLM only reasons over a prepared payload.** Cheap, reproducible, auditable.
2. **`SOUL.md` is a refusal policy as much as a personality.** Grounding rules belong in the agent's standing instructions.

What the reference does *not* have — and therefore what "extending the scope" means here: real retrieval (it dumps
whole markdown files), a domain database, an API, an OpenAPI contract, tests, a frontend, CI/CD, observability,
security artifacts, or reproducibility. Our project keeps the pattern and builds the missing engineering around it.

## 3. Target architecture

```text
Telegram users
      |  long polling (no inbound ports, works behind NAT, no VPS)
      v
hermes            Hermes Agent gateway in its own container
      |           SOUL.md, AGENTS.md context, skills/, subagents/, hooks/, cron jobs
      |  MCP (stdio), read-only, allowlisted tools
      v
mcp-server        tool schema -> backend REST; returns compact JSON sized for an LLM
      |  REST (contract = openapi.yaml)
      v
backend           FastAPI + SQLAlchemy + Alembic; read paths for agent and dashboard
      ^                                        ^
      |                                        |
ingest            scheduler + 10 req/min bucket   frontend (Next.js): data freshness, fixtures,
      |           bronze JSON -> normalized tables   standings, agent conversation log, eval
      |           run ledger, idempotent upserts      results, admin controls
      v
football-data.org v4 (free tier)          Postgres 16 + pgvector (SQLite for dev)
```

Cross-cutting, in the same Compose project: `observability/` (OTel collector -> Prometheus, Loki, Tempo, Grafana +
alerts), `security/` (scan outputs, capability table, threat model, policy), `ops/` (runbooks, incident drill
evidence), `evals/` (golden questions), `tests/` (unit, integration, e2e), `.github/workflows/` (CI, CD, PR audit, scans).

## 4. Data source: free-tier reality check

Verified against football-data.org pricing/coverage/policies pages:

- **Free plan: 12 competitions** — Premier League, Championship, Bundesliga, Serie A, La Liga, Ligue 1, Eredivisie,
  Primeira Liga, Brasileirao Serie A, Champions League, European Championship, World Cup.
- **10 requests/minute** on the free plan (30 on Standard, 60 above). Unauthenticated clients: 100 requests/24h.
- **Scores and schedules are delayed** on the free tier; **fixtures and league tables** are included.
- Live scores, odds, lineups and advanced stats are paid tiers.

Design consequences that are now hard rules in `AGENTS.md`:

- Batch ingestion only, with a token bucket, backoff, and caching; no upstream call in a request path.
- Every answer that contains a score or a table carries a **data timestamp** and the source.
- The agent must state that data is delayed rather than imply it is live.
- Early spike task: confirm which sub-resources (scorers, lineups, head-to-head) actually return on free — the
  product must degrade gracefully, not crash on 403.

## 5. Scope extensions (beyond the original brief)

| # | Extension | Why / what it adds |
| --- | --- | --- |
| A | **Real RAG layer** — curated football knowledge corpus embedded into pgvector, retrieved with a `search_knowledge` tool, hybrid with structured SQL answers | The reference "RAG" reads whole files. This makes retrieval a first-class, measurable component and grounds the qualitative questions (formats, tiebreakers, promotion rules, glossary) that no table can answer |
| B | **Ingestion as a product** — scheduled container, bronze/silver/gold layers, run ledger, idempotent upserts, freshness endpoint | "Scheduled workflow" in the brief; makes data quality observable and testable |
| C | **API + MCP tool surface** — OpenAPI-first backend, thin MCP server exposing 6-8 read-only tools | Tool calling needs a narrow, typed, allowlisted surface, not a SQL hole |
| D | **Frontend dashboard** (Next.js) — freshness, fixtures/standings explorer, agent conversation log + review flags, eval results, admin controls | The brief had no frontend; criteria 3 and 4 require one, and it is genuinely useful for auditing agent behavior |
| E | **Eval harness** — golden question set, accuracy/groundedness/refusal scoring, run in CI | Turns "the agent is accurate" into a checkable claim with a regression signal |
| F | **Agent extension pack** — project instructions, a reusable skill, a verifier subagent, the MCP server, a guardrail hook, a plugin package, permission notes | Course criterion 12, and it is the natural next layer for a Hermes project |
| G | **Observability + incident response** — OTel instrumentation, Prometheus/Loki/Tempo/Grafana, actionable alerts, bounded read-only responder, evidence packet | Criterion 13; the reference project has no idea whether it still works |
| H | **Security and audit** — capability table, MCP threat model, Semgrep + dependency/image scans, agent-supply-chain scan, PR audit, prompt-injection tests, AI tool/data policy | Telegram input is untrusted; an agent with data access is attack surface |
| I | **AI-assisted workflow artifacts** — prompt bank, task/PR log, review log, `_docs/ai-usage-report.md`, Hermes used to build itself | Criterion 2 |
| J | **Containerization and reproducibility** — one `docker compose up` brings the whole system up; Make targets; `.env.example`; pinned versions | Criteria 8 and 14 |

## 6. Deployment investigation — can Hugging Face Spaces host this for free?

Asked and answered in this round, because criterion 10 wants a public URL while the brief says "localhost only".

Findings (Hugging Face docs, pricing page, and forum threads, July 2026):

- **Docker/Gradio Spaces on compute are no longer free.** Hub docs: "Static Spaces are free for everyone. Gradio and
  Docker Spaces run on compute and require a paid plan to create: PRO for personal accounts, Team or Enterprise for
  organizations." The CLI returns: "hosting Gradio and Docker Spaces on free cpu-basic requires a PRO subscription."
  The change landed around 8 July 2026 with no announcement ([forum thread](https://discuss.huggingface.co/t/docker-sdk-now-marked-as-paid-when-creating-a-new-space/177580),
  [docs PR](https://github.com/huggingface/hub-docs/pull/2624)). PRO is $9/month.
- Even with PRO, the shape is wrong for us: **one container per Space**, exposed port `7860` (`app_port`), 16 GB RAM /
  2 vCPU / **50 GB non-persistent disk**, outbound network limited to ports 80, 443 and 8080, container runs as UID 1000.
  No Compose, so Postgres + backend + MCP + Hermes + frontend + observability cannot be deployed as one unit.
- **Sleep policy:** on free hardware a Space stops executing after **48 hours of inactivity** and cold-starts on the
  next request. A long-polling Telegram bot that sleeps is a dead bot — and the "warm ping" workaround is fragile.
  Only paid hardware tiers are effectively always-on.

**Verdict: no.** HF Spaces cannot host the dockerized system for free, and it is a poor architectural fit even when
paid. We keep the **free Cloudflare tunnel** as the public URL for the local stack. That is not a workaround, it is a
reasonable reading of criterion 10: the system runs as containers on the developer machine and is reachable at a
public HTTPS URL, with the Telegram bot public by nature.

Resulting deployment story for criterion 10:

1. **Primary, public:** the Telegram bot — reachable from any device, no hosting required beyond outbound polling.
2. **Public URL:** a Cloudflare named tunnel (`cloudflared`) -> stable HTTPS URL for the dashboard and read-only demo
   API, with a post-deploy smoke check on `/health` and `/meta/freshness`.
3. **Optional, free:** publish the *built dashboard* as a **Static Space** on Hugging Face (static Spaces are still
   free for everyone) as a showcase; it points at the tunnel API. No compute, no sleep problem.
4. **Documented fallback:** if a genuinely hosted instance is ever wanted, a $9 HF PRO Space or a free-tier container
   host can serve the dashboard — the Compose file stays the source of truth.

## 7. Coverage of the 14 draft project criteria

| # | Criterion (top band) | How this project shows it | Artifact |
| --- | --- | --- | --- |
| 1 | Problem description (2) | README + spec: what the agent answers, free-tier data limits, delayed-data disclosure, example dialogues, expected behavior | `README.md`, `_docs/product-spec.md` |
| 2 | AI-assisted workflow (2) | Versioned prompt bank, AGENTS.md context, spec -> task -> implement -> independent verify loop, review/rejection logs, Hermes dogfooding | `prompts/`, `AGENTS.md`, `_docs/ai-usage-report.md` |
| 3 | Tech & architecture (2) | Architecture diagram with the role of every component; why MCP, why a thin tool layer, why batch ingestion | `_docs/architecture.md#` |
| 4 | Frontend (3) | Next.js dashboard, single typed API client, component + unit tests with run instructions, Playwright coverage of core flows | `frontend/`, `tests/e2e/` |
| 5 | API contract (2) | `openapi.yaml` written before code, backend implemented against it, contract test asserting spec/app parity | `openapi.yaml`, `backend/tests/test_contract.py` |
| 6 | Backend (3) | Layered FastAPI (router/service/repo), pydantic models from the spec, pytest on core endpoints, typed errors, documented | `backend/`, `backend/tests/` |
| 7 | Database (2) | SQLite (dev) <-> Postgres (prod) via `DATABASE_URL`, Alembic migrations, pgvector corpus, seed script, documented schema | `_docs/data-model.md`, `db/` |
| 8 | Containerization (2) | One `docker compose up` starts db, ingest, backend, mcp-server, hermes, frontend, observability; healthchecks; `make up` | `docker-compose.yml`, `Makefile` |
| 9 | Integration testing (2) | Tests against the real Compose stack: ingest -> DB -> API -> MCP -> agent reply; kept separate from unit tests | `tests/integration/` |
| 10 | Deployment (2) | Public Telegram bot + Cloudflare tunnel URL for dashboard/API + post-deploy smoke check (see §6) | `_docs/deployment.md` |
| 11 | CI/CD (2) | Actions: lint, unit, integration, evals, image build -> on merge to main migrate, redeploy, smoke check, rollback path | `.github/workflows/ci.yml`, `deploy.yml` |
| 12 | Agent extension pack (2) | Project instructions, reusable `SKILL.md` workflow, verifier subagent, MCP tool server, guardrail hook, plugin package, permission notes | `skills/`, `subagents/`, `mcp-server/`, `hooks/`, `plugins/`, `docs/permissions.md` |
| 13 | Security/audit/DevOps (2) | PR-Agent audit output, Semgrep + dependency/image scan findings, agent & MCP capability/threat tables, incident drill evidence packet, AI tool/data policy | `security/`, `ops/`, `observability/` |
| 14 | Reproducibility (2) | `make setup && make up && make e2e`, `.env.example`, pinned versions, documented free-tier key setup, seed data | `README.md`, `Makefile` |

## 8. Milestones

| M | Goal | Exit condition |
| --- | --- | --- |
| M0 | Scaffold | Repo, AGENTS.md, spec, scoping, git initialized |
| M1 | Contract + schema | `openapi.yaml` + migrations applied in Compose; contract test green |
| M2 | Ingestion | Daily run loads 12 competitions into Postgres; ledger row per run; rate limiter proven by test |
| M3 | API | Backend endpoints pass unit + integration tests against the real stack |
| M4 | Agent | MCP tools wired into Hermes; Telegram answers grounded questions end to end |
| M5 | Dashboard + evals | Frontend tested; golden-question eval run in CI with a pass threshold |
| M6 | Ops + hardening | CI/CD, observability with one actionable alert, incident drill, security artifacts, AI usage report |

## 9. Open decisions

1. **Dashboard hosting:** Cloudflare named tunnel (needs a domain) vs. quick tunnel (random URL, changes on restart).
   Default: named tunnel, quick tunnel documented as fallback.
2. **RAG depth:** pgvector inside Postgres (default, one store) vs. a separate vector service (not worth it at this size).
3. **Scope guard:** keep the frontend to read-only observability first; write actions (pause ingestion, re-run job) are
   admin-only and audited.
4. **Model choice:** Hermes' provider is configurable; the eval harness must run against a pinned model so scores are comparable.
