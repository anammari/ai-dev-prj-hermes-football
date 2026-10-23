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

Only `backend` publishes a host port (`8000`). No Docker socket. The corpus is mounted read-only. See
[`setup-and-review.md`](setup-and-review.md) for the service list and commands.

## 5. How the 12 course criteria are covered

| # | Criterion | Status | Evidence and gap |
| --- | --- | --- | --- |
| 1 | Problem description | Met | This file §1–3; football answers are late or invented, so we store and cite them |
| 2 | Product specification | Partly | [`product-spec.md`](product-spec.md), [`openapi.yaml`](../openapi.yaml). Gap: no public task tracker; moving the plan to GitHub Issues is later |
| 3 | Agent team | Met | [`agent-team.md`](agent-team.md), [`ai-usage-report.md`](ai-usage-report.md), [`prompts/`](../prompts/README.md) |
| 4 | Context management | Met | [`AGENTS.md`](../AGENTS.md) plus modular docs; rules change in the same PR as behaviour |
| 5 | Application | Open | Backend, MCP tools and Telegram agent work. Gap: dashboard |
| 6 | Testing | Partly | 358 unit, 38 integration, contract drift tests. Gap: one command for both; no e2e until dashboard |
| 7 | Containerization | Partly | `make up` starts six services, health checks, one port. Gap: dashboard |
| 8 | Deployment | Partly | Telegram long polling; tunnel for dashboard planned. Gap: no public deployment yet |
| 9 | CI/CD | Open | Local gates only; workflows, deploy, rollback are later |
| 10 | Observability | Open | OTel/Prometheus/Loki/Tempo/Grafana planned |
| 11 | Alerting | Open | Staleness or repeated failure alert planned |
| 12 | On-call agent | Open | Cron digests and answer-verifier planned |

## 6. Plan and results

| Stage | Scope | Status |
| --- | --- | --- |
| 1 | Schema, corpus manifest, chunker, local embedder, one note indexed | Done |
| 2 | Upstream collection, bronze store, loaders, run ledger, scheduler, re-indexing, delay polling | Done |
| 3 | Read-only API against the contract, read-only role, freshness report, drift tests | Done |
| 3b | Two model-first routers compared on 85 hand-labelled questions; `clef:cloud` selected | Done |
| 4 | Safety gate, MCP tools, Telegram gateway, reviewed notes, scorer tool | Done |
| 5 | Dashboard and golden-question scoreboard | Next |
| 6 | CI/CD, observability, alerting, on-call, security artifacts, final Mermaid diagram in README | Later |

**Routing result.** Independent 60-question holdout, authored and audited separately, frozen, one run. Prompt v1:
gated macro-F1 **0.979**; adversarial 8/8, fabricated 4/4, refusal 3/3, unsupported 4/4, zero false refusals. Prompt
v2 added the complexity label; the regression run scored **0.960**, all gates still passed. Evidence:
[`evals/routing/results/`](../evals/routing/results/2026-10-21T21-42-43Z.md).

**Agent result.** Eight read-only MCP tools, simple and complex answer paths, thirteen reviewed notes, 41 chunks in
pgvector, and one `agent_turns` row per answered turn. The public review bot is
[@review_soccer_bot](https://t.me/review_soccer_bot). The live Telegram smoke test is the owner's step; `make ask`
and integration tests exercise the same pipeline.

**Known gap.** Top-scorer data is now served by `get_top_scorers`; lineups, odds, live scores and xG are not available.

## 7. Still to decide

1. **Dashboard address:** temporary Cloudflare tunnel for the demo, no permanent hostname. A permanent tunnel would
   need a machine that never sleeps.
2. **Dashboard permissions:** read-only at first; any action that changes data is admin-only and logged.
3. **Licence:** no licence chosen yet.

## 8. Where to look next

- Run and test: [`setup-and-review.md`](setup-and-review.md)
- Requirements and acceptance criteria: [`product-spec.md`](product-spec.md)
- Notes and retrieval: [`rag.md`](rag.md)
- Tables and open items: [`data-model.md`](data-model.md)
- Sources for every note: [`notes-sources.md`](notes-sources.md)
- Decisions: [`decisions/`](decisions/README.md)
