# Scoping — Hermes Football

What the project is, what the free data allows, how the 12 course criteria are covered, and what is next. Technical
requirements live in [`product-spec.md`](product-spec.md); the API contract in [`openapi.yaml`](../openapi.yaml).

## 1. What it is

A Telegram bot that answers football questions accurately. It collects fixtures, results, tables and scorer
snapshots daily from the free football-data.org API into Postgres, and keeps a small hand-written corpus for rules
and definitions. Answers come from one of those two sources, never from the model's memory.

The public entry point is the bot. Everything runs locally in Docker Compose; there is no server to rent.

## 2. What the free data allows

Checked with a real free key on 2026-10-10, before writing code:

- Fixtures, results and league tables work, with filters by date, matchday and season.
- Squads and top scorers are exposed on the free key, although the pricing page calls them paid. Treat them as
  plan-dependent.
- Odds are not usable: the field only says "activate Odds-Package".
- Head-to-head counts are wrong (0–0–0 for a pair with three meetings), so we count meetings from stored results.
- The plan returned **13 competitions**, not the advertised 12 (Copa Libertadores is the extra). Never hardcode 12.
- Scores and schedules are delayed. Measured delay is about 1.5–3 minutes, median 104 s over ten polls. Always show
  the data timestamp and never call delayed data live.

The collector paces on the provider's own headers, 10 requests/minute. A full run costs roughly 130–350 calls.

## 3. The two roads, and two answer depths

**Database** for numbers, dates and tables: scores, fixtures, positions, form, head-to-head, freshness, scorer
snapshots. **Notes** for written rules: formats, tiebreakers, promotion/relegation, definitions, coverage limits.
If neither supports an answer, the bot refuses.

Every message goes to `clef:cloud`, which returns four labels: road, tool, safety, and `simple` or `complex`.
`clef:cloud` sees the user message and a fixed label set only — never retrieved text, never tool output. No regex and
no deterministic pre-router.

- **Simple:** one tool or one note retrieval, local deterministic answer. The simple path keeps tool output and note
  text on the machine.
- **Complex:** planner chooses up to four allowlisted tools, or retrieves eight note passages; `beam:cloud` composes
  the answer from those results. A citation check and a focused second-model claim check run before sending; a
  failure falls back to the deterministic composer. This path sends results to `beam:cloud`; signed off for complex
  questions only.

**Safety gate.** Any `safety` label other than `safe` refuses before a tool or note is touched. A `database` choice
with no tool refuses as `unsupported_tool`. An unreachable model fails closed with `route_source: fallback`.

## 4. Where it runs

One Compose project:

```text
Telegram long polling -> hermes gateway -> MCP HTTP -> backend -> Postgres
                                      \-> clef:cloud (routing) / beam:cloud (complex answers)
ingest scheduler -> football-data.org; ollama (local embeddings) -> pgvector
```

Only `backend` (`8000`) and `frontend` (`3000`) publish host ports. No Docker socket. The corpus is mounted read-only.
The dashboard fetches server-side, so its tokens never reach the browser; a tunnel is demo-only. See
[`setup-and-review.md`](setup-and-review.md) for the service list and commands.

## 5. How the 12 course criteria are covered

| # | Criterion | Status | Evidence and gap |
| --- | --- | --- | --- |
| 1 | Problem description | Met | This file §1–3; football answers are late or invented, so we store and cite them |
| 2 | Product specification | Partly | [`product-spec.md`](product-spec.md), [`openapi.yaml`](../openapi.yaml). Gap: no public task tracker; moving the plan to GitHub Issues is later |
| 3 | Agent team | Met | [`agent-team.md`](agent-team.md), [`ai-usage-report.md`](ai-usage-report.md), [`prompts/`](../prompts/README.md) |
| 4 | Context management | Met | [`AGENTS.md`](../AGENTS.md) plus modular docs; rules change in the same PR as behaviour |
| 5 | Application | Met | Backend, MCP tools, Telegram agent and the dashboard (`frontend/`, seven routes) over one contract |
| 6 | Testing | Met | 450 unit, 41 integration, 27 dashboard unit, 6 browser tests, contract drift tests. Evidence: `make test`, `make itest`, `make frontend-test`, `make e2e` |
| 7 | Containerization | Met | `make up` starts eight services with health checks; two published ports, plus a loopback-only Grafana in the opt-in obs profile |
| 8 | Deployment | Partly | Telegram long polling; the dashboard runs locally and a Cloudflare tunnel is demo-only. Gap: no permanent public host |
| 9 | CI/CD | Met | `.github/workflows/ci.yml` gates lint, unit/contract, dashboard, security scans, integration and build; nightly re-scans; `make ci` is local parity |
| 10 | Observability | Met | OTel collector → Prometheus/Loki/Tempo → Grafana on `127.0.0.1:3001`; five signals, two dashboards, no app `/metrics` route |
| 11 | Alerting | Met | `ingest_unhealthy` (stale / repeated failure / stuck) evaluated by `agent/oncall`; log + `alerts.json` + `hermes_alert_firing`; drill in `ops/drills/` |
| 12 | On-call agent | Met | daily read-only digest in the `oncall` container; alert loop; eval-age check; no model, no write path |

Ten criteria are **Met**. Two are **Partly**, each with a named gap: 2 has no public task tracker, and 8 has no
permanent public host. None is **Open**.

## 6. Plan and results

| Stage | Scope | Status |
| --- | --- | --- |
| 1 | Schema, corpus manifest, chunker, local embedder, one note indexed | Done |
| 2 | Upstream collection, bronze store, loaders, run ledger, scheduler, re-indexing, delay polling | Done |
| 3 | Read-only API against the contract, read-only role, freshness report, drift tests | Done |
| 3b | Two model-first routers compared on 85 hand-labelled questions; `clef:cloud` selected | Done |
| 4 | Safety gate, MCP tools, Telegram gateway, reviewed notes, scorer tool | Done |
| 5 | Dashboard and golden-question scoreboard | Done |
| 6 | CI/CD, observability, alerting, on-call, security artifacts, final Mermaid diagram in README | Done |

**Routing result.** Independent 60-question holdout, authored and audited separately, frozen, one run. Prompt v1:
gated macro-F1 **0.979**; adversarial 8/8, fabricated 4/4, refusal 3/3, unsupported 4/4, zero false refusals. Prompt
v2 added the complexity label; the regression run scored **0.960**, all gates still passed. Evidence:
[`evals/routing/results/`](../evals/routing/results/2026-10-21T21-42-43Z.md).

**Agent result.** Eight read-only MCP tools, simple and complex answer paths, thirteen reviewed notes, 41 chunks in
pgvector, and one `agent_turns` row per answered turn. The public review bot is
[@review_soccer_bot](https://t.me/review_soccer_bot). The live Telegram smoke test is the owner's step; `make ask`
and integration tests exercise the same pipeline.

**Dashboard result.** Seven server-rendered routes over the same 19-operation contract, with provenance on every
factual page and no token in the browser. The one write is the review decision, behind `API_ADMIN_TOKEN` and a
column-scoped `agent_admin` role; the ingest trigger stays a documented 404 until the M6 queue exists.

**Eval result.** A 48-question golden set, authored independently and audited by a second reviewer, scored end to end
through the shipped pipeline: `make eval` stores a run in `eval_runs`/`eval_results` and an artifact, and the
scoreboard draws one series per set hash with the 0.90 target. The first live run passes routing (macro-F1 0.928,
retrieval 0.906) and fails the gate on completeness (0.858) and three missing citations - all real product misses it
kept red rather than tuned away: `inter milan vs juventus` defeats the name resolver, two answerable questions routed
`clarify`, and one fabricated-fact question asked back instead of refusing (fabricated 2/3). Scores are deterministic:
no model judge, and therefore no new cloud egress.

**Operations result.** CI runs the pull-request gates on a GitHub runner and keeps the eval and the router suite
local, because both need the signed-off cloud models. The observability stack is opt-in: five containers on an
internal network, Grafana loopback-only, dashboards for API/gateway/MCP/ingest/on-call, and no new application route.
One alert (`ingest_unhealthy`) is evaluated by the on-call container against the ledger and demonstrated by a real
drill, in minutes, in `ops/drills/2026-10-27-ingest-stale.md`. The on-call digest is read-only and carries no message
text. Security artifacts are `security/capability-table.md`, `security/threat-model.md` and the gitleaks/pip-audit/
pnpm-audit/trivy scans. The integration suite went from red to green on the way in: a knowledge search took
13-18.5 s while the MCP server waited 15 s, so the first notes question after a restart failed; the timeout budget
is now nested and asserted (`tests/test_timeout_budget.py`).

**Known gap.** Top-scorer data is now served by `get_top_scorers`; lineups, odds, live scores and xG are not available.
The ingest trigger, the three eval-surfaced agent misses, the dashboard login/permanent host and the licence are
recorded follow-ups in [`follow-ups.md`](follow-ups.md).

## 7. Still to decide

1. **Dashboard address:** temporary Cloudflare tunnel for the demo, no permanent hostname. A permanent tunnel would
   need a machine that never sleeps and a login; both are out of scope.
2. **Dashboard permissions:** read-only, plus the one admin write (the review decision), which is admin-token only and
   recorded on the row. There is no login; the tunnel is demo-only and message text is masked by default.
3. **Licence:** deliberately deferred. A public repository without a licence is all-rights-reserved, which is the
   conservative default; choosing one grants rights and is the owner's decision. Recorded in
   [`decisions/0009`](decisions/0009-m6-operations.md) and [`follow-ups.md`](follow-ups.md).
4. **Ingest trigger:** `POST /admin/ingest-runs` remains a documented `404`; closing it needs a queue table, a second
   API write role, a scheduler restructure and a contract-visible queue state (v0.5.0). Design sketch in
   [`follow-ups.md`](follow-ups.md).

## 8. Where to look next

- Run and test: [`setup-and-review.md`](setup-and-review.md)
- Requirements and acceptance criteria: [`product-spec.md`](product-spec.md)
- Notes and retrieval: [`rag.md`](rag.md)
- Tables and open items: [`data-model.md`](data-model.md)
- Sources for every note: [`notes-sources.md`](notes-sources.md)
- Decisions: [`decisions/`](decisions/README.md)
