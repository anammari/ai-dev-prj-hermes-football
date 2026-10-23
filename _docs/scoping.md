# Scoping — Hermes Football

What this file is: the plain-English picture of the project — what we are building, what we checked, what each piece
is for, and how it covers the course requirements. If you want the technical detail (requirements, acceptance
criteria, data model), read `_docs/product-spec.md` instead. This file is the one to read first.

---

## 1. What we are building

A Telegram bot that answers football questions correctly.

You ask it something like "how are Arsenal doing?" or "when do they play Chelsea?", and it replies with a real answer
taken from a database we keep up to date — not from the model's memory, which is exactly where football bots usually
go wrong.

Three things make it work:

1. **We collect the data ourselves.** Every day a scheduled job pulls fixtures, results and tables from
   football-data.org (a free football API) and stores them locally.
2. **The bot looks things up before it answers.** It has a small set of "tools" — one for the league table, one for
   fixtures, one for recent form, and so on. To answer, it asks a tool, gets real rows back, and writes the sentence
   from those rows. If the data isn't there, it says so instead of guessing.
3. **It knows the things a table can't hold.** Competition rules, how the playoffs work, what "aggregate" means, why
   our scores are a few minutes behind — that lives in our own notes, which the bot can search.

Everything runs on your laptop in Docker: one command starts the whole system. There is no server to rent.

## 2. What we took from the tutorial project

The inspiration is a public tutorial project (`MariyaSha/hermes_business_agent`) where a business answers customer
questions from its own documents. It is only five files, and two ideas in it are worth copying:

- **It does the counting in code, and only asks the AI to explain.** A plain Python script totals up the day's
  conversations; the AI's only job is to write the report. Cheap, repeatable, and easy to check.
- **It writes the rules down as instructions.** Its `SOUL.md` doesn't just set the personality — it tells the agent
  "these files are the truth, never invent a price, and if you don't know, say so".

What it does *not* have: a real database, an API, tests, a dashboard, automatic deployment, or any way to tell whether
it is still working. That is the engineering we are adding around the same idea.

## 3. The football data we can actually get

The free plan is genuinely free, but it is not unlimited, and the limits shape the design.

**The advertised terms:** 12 competitions, 10 requests per minute, scores and schedules arrive delayed, fixtures and
league tables included. Live scores, odds, lineups and advanced statistics are paid tiers.

**What we found when we tested it** (a real free key, 10 October 2026 — we called every part of the API we planned to
use before writing any code):

| Question we asked the API | What came back |
| --- | --- |
| League tables? | Yes |
| Fixtures and results? | Yes, with filters by date, matchday and season |
| Player squads? | **Yes** — 24 players for Arsenal, 48 for Fluminense. We expected this to be paid; it isn't |
| Top scorers? | **Yes** — available on the free plan |
| Head-to-head records? | The data arrives, but the win/draw/loss counts are wrong (0–0–0 for a pair with 3 meetings), so **we count them ourselves** |
| Betting odds? | No — the field exists but only says "activate Odds-Package" |
| How many competitions? | **13, not the 12 advertised** — the extra one is the Copa Libertadores |
| A competition we're not allowed? | The API refuses with "not within your permissions" — we must show "no data", never an empty table |
| Several competitions in one call? | Yes — which is how we stay comfortably under 10 calls a minute |
| How delayed are the scores? | **About 1.5-3 minutes**, measured on 2026-10-12/13 (match 555033) and re-measured live on 2026-10-13 (match 555032, median lag 104s over 10 polls): the score is published during play and the final score arrives with the `FINISHED` status, so there is no scoreless-finished window. The status can briefly flip back to `TIMED` while a match is in play. `make score-delay` reproduces the measurement; run it while a match is on |

One more helpful detail: the API tells us how many calls we have left in the current minute, so we pace ourselves on
its own numbers instead of guessing.

## 4. When the database answers, and when our notes do

There are two ways to answer a football question, and mixing them up is how bots start making things up.

- **From the database** — the answer is a number, a date, or a table. The bot asks a tool, the tool runs a query, rows
  come back, the bot writes the sentence. Nothing needs to be "searched".
- **From our notes** — the answer is a sentence that someone wrote down: a rule, a format, a definition, or a policy
  of ours. Here the bot searches our own notes and answers from the passage it finds, citing where it came from. The
  notes are written in English, one topic per file, and each one is listed in a manifest with the source it came from,
  so we can say what should exist and notice what is missing.

**Questions the database answers on its own:**

- "Where are Arsenal in the table?" — position and points, straight from the league table.
- "When do Arsenal play Chelsea?" — the fixture date, straight from the fixtures.
- "What was the score?" — the result, straight from the results.
- "How have Arsenal done in their last five?" — wins, draws and losses, counted in the database.
- "How many goals has Haaland scored?" — one row from the top-scorers table.
- "Who does Arsenal beat more often, Chelsea or Spurs?" — the head-to-head counts, which we calculate ourselves.
- "How up to date is this?" — the timestamp on the data.

**Questions only our notes can answer** (this is what the note-searching, "RAG", is for):

- Competition formats — "how does the Championship promotion playoff work?" Nothing in a table describes a bracket's rules.
- Tiebreakers — "what happens if two teams in Serie A finish level on points?" Goal difference or head-to-head is a rule, not a row.
- Qualification and relegation — "how many teams go down from the Bundesliga, and how do you qualify for the Champions League?".
- Our own data policy — "is that score live, and why is it delayed?" The delay and coverage policy is prose we wrote.
- Coverage limits — "why can't you give me lineups?", "do you cover the Greek league?" — so the bot explains the limit instead of claiming no data exists.
- Glossary — "what does aggregate mean in a two-legged tie?", "what is a clean sheet?".
- Multi-hop rules questions — "if a team finishes fifth and also wins the cup, do they still get a European place?" The answer is spread across several notes, which is where searching beats a lookup.

**The one-line rule:** if the answer is a number, a date or a table, it comes from the database. If it is a sentence
from a document, it comes from our notes. A football bot that searches documents for a score is doing it wrong, and
so is one that tries to query a database for the meaning of "aggregate".

**How the bot decides which way to look.** Not by vibes, and not by regex. Every message goes to a decision model,
which picks one of four surfaces — database, notes, ask back, refuse — and also says whether the answer is **simple**
(one stored fact or one note) or **complex** (several facts or notes combined). The surface and complexity are written
down with the answer, so a wrong turn shows up on the dashboard and in the scoreboard. Two models were compared on the
same 85 questions and the same request (section 8); the cloud model routed better and was **selected on 2026-10-20**.
The router is wired behind the hard safety gate added in M4; the independent holdout is recorded in section 8.

**Simple and complex answer paths.** A simple question keeps the single tool (or one note retrieval) and the local
deterministic composer: no second model, no tool output leaving the machine. A complex question lets the gateway plan
up to four allowlisted tools, or retrieve up to eight note chunks, and hands the collected results to **`beam:cloud`**
for a grounded, cited answer. A citation check and a focused second-model claim check run before sending; if
either fails, the deterministic composer answers instead. The simple path stays local. The complex path is the one place where tool output and note text leave the
machine; the owner signed that egress off on 2026-10-22 for complex questions only.

## 5. Extra work beyond the first brief

The first brief was: a Telegram bot, a free football API, daily data collection, an API in front of the database, all
in Docker. To make that a real, checkable product — and to cover the course requirements — we added:

| Extra piece | Why it earns its place |
| --- | --- |
| **Notes the bot can search** (RAG) | The tutorial lets the agent read whole documents. Real searching makes the qualitative answers — the ones in section 4 — measurable instead of lucky |
| **Data collection treated as a product** | Daily run, a log of every run, no duplicates, and a visible "how fresh is this?" answer. The brief said "scheduled"; this makes it trustworthy |
| **A wrapped API with a written contract** | The bot gets a small, typed, read-only set of tools instead of a database password |
| **A web dashboard** | Shows data freshness, the matches, what the bot answered, and how the answers scored. The brief had no front end, and the course requires one — it is also how you actually audit a bot |
| **An answer-quality scoreboard** | A fixed set of test questions ("golden questions") that the bot answers on every change, so "it works" is a number, not a feeling |
| **The bot's own tool kit** | Reusable instructions, a checker that verifies answers, a guardrail that blocks risky calls, and a written list of what the bot is allowed to do |
| **Watching and incident practice** | Logs, metrics and one alert that fires when something actually hurts users, plus a rehearsal of "what do we do when it breaks at night" |
| **Security and audit work** | A list of everything the bot can reach, scans of our own code, and tests that try to trick the bot through a Telegram message |
| **A written record of how AI was used** | The course asks for it, and it is how you review a project built mostly by agents |
| **A written list of the notes** | The bot can only cite what exists. A manifest names every note, where it came from and who owns it, and the build fails if a note or an entry goes missing |
| **A local model for notes, a cloud model for routing** | `embeddinggemma:300m` turns notes into searchable numbers on the laptop, so note text never leaves the machine. Routing uses `clef:cloud`, signed off in M3b: it is better at the four-way choice, at the cost of sending the user's message to Ollama's cloud |

## 6. Where it runs (and why not on Hugging Face)

Everything runs locally in Docker — the bot, the API, the database, the collector, the dashboard, the monitoring.
Nothing is installed on your machine except Docker itself.

The public part is the **Telegram bot itself**: Telegram works by the bot calling out to Telegram, so it needs no
incoming port, no static IP and no server. That is why "local only" and "a bot anyone can message" are not in
conflict.

For the dashboard we use a **free Cloudflare tunnel** — a public web address that points at the local stack. We also
have the option to publish the dashboard as a free static page on Hugging Face.

**The public exposure is for the demo, not permanent.** The Telegram bot and the tunnel are switched on for one short
recorded demo that proves the deployment criterion end to end — a real message answered by the bot, the dashboard
reached over its public address — and shut down afterwards. The laptop is the server only for those minutes; nothing
stays listening on the internet, and no tunnel, hostname or credential outlives the recording. The demo is the
evidence, `_docs/deployment.md` records what was run and where the recording lives, and the always-on alternative
(a small always-on machine) is explicitly not this project's plan. That keeps the honest position: local-first data,
public access demonstrated rather than rented.

**Could Hugging Face Spaces host the whole thing for free? No.** Docker Spaces on free hardware now require a paid
plan (about $9/month), and even then one Space holds a single container — no database, no dashboard, no monitoring
alongside it. Its disk is wiped on restart, and free Spaces fall asleep after 48 hours of quiet, which for a Telegram
bot means a bot that stops answering. It is the wrong shape for this project, not just the wrong price.

## 7. How the 12 course criteria are covered

The course now scores **12 criteria worth 24 points; 10 points pass**. The table maps each one to an artifact in
this repo and names the gap where one exists. It is evidence, not a self-score.

| # | Criterion | Evidence in this repo | Status / gap | Where to look |
| --- | --- | --- | --- | --- |
| 1 | Problem Description | The README states the problem, what the bot answers, what the free data allows, and what it says when it does not know | Met | `README.md`, `_docs/product-spec.md` |
| 2 | Product Specification | The product spec and the API contract exist and are versioned; each milestone names acceptance criteria | **Gap:** no public task tracker with evidence the agents used it; the milestone/PR record is not a substitute | `_docs/product-spec.md`, `openapi.yaml`, `_docs/scoping.md` §8 |
| 3 | Agent Team Specification | [`_docs/agent-team.md`](agent-team.md) defines the owner, the coding agent, the independent reviewers and how they hand off; prompts and the AI-usage report make the process inspectable | Met | `_docs/agent-team.md`, `AGENTS.md`, `prompts/`, `_docs/ai-usage-report.md` |
| 4 | Context Management | `AGENTS.md` is the entry point and points to modular docs: scope, spec, data model, decisions, RAG, AI usage, the routing comparison | Met | `AGENTS.md`, `_docs/` |
| 5 | Application | Backend, Postgres, ingestion, the MCP tool server and the Telegram gateway work end to end; the dashboard is M5 | **Gap:** no frontend yet, so it is not a full-stack application | `backend/`, `db/`, `ingest/`, `mcp_server/`, `agent/gateway/` |
| 6 | Testing | Unit tests (`make test`) and integration tests against the Compose stack (`make itest`) exist and pass | **Gap:** they are separate commands; the course asks for both with one command | `tests/`, `tests/integration/`, `Makefile` |
| 7 | Containerization | One `make up` starts `db`, `ollama`, `backend`, `mcp-server`, the `hermes` gateway and the ingest scheduler, with health checks and one published port | **Gap:** the frontend is not in the Compose project yet | `docker-compose.yml`, `Makefile` |
| 8 | Deployment | The demo-scoped public path is written down (§6); the Telegram bot needs no inbound port | **Gap:** no working deployment yet; the demo tunnel is planned, not shown | `_docs/scoping.md` §6 |
| 9 | CI/CD | No workflows yet; local gates are `make test`, `make lint` | **Gap:** no CI on pull requests, no deploy/rollback | `.github/workflows/` (missing), `Makefile` |
| 10 | Observability | No telemetry yet; the plan is OTel -> Prometheus/Loki/Tempo/Grafana | **Gap:** no metrics, traces or correlated logs | `_docs/product-spec.md` F10, `observability/` (missing) |
| 11 | Alerting on User Impact | No alert yet; the planned alert is data staleness or repeated agent failures | **Gap:** no alert rules or incident rehearsal | `_docs/product-spec.md` F10, `ops/` (missing) |
| 12 | On-Call Agent | No on-call agent yet; Hermes cron jobs and an answer-verifier are planned | **Gap:** no agent wakes on an alert | `hermes/` (M4), `subagents/` (missing) |

At the moment the honest total is **10 of 24**: criteria 1, 3 and 4 are met, 2, 6, 7 and 8 are partly met, and 5,
9, 10, 11 and 12 are open. The open gaps are the M4-M6 work, not decoration.

## 8. The plan

| Step | What it means | Done when |
| --- | --- | --- |
| M0 | Empty repo, scope, spec, API contract | Done |
| M1 | Database schema and the first migration, matching the contract, including the notes table, the list of notes and the small model that turns text into searchable numbers | Tests against the real stack pass, and a note file can be indexed end to end |
| M2 | Daily collection from the football API, plus re-indexing any note that changed | A day's data lands with a run log, the real score delay is measured, and editing a note changes what the bot answers |
| M3 | The wrapped API | The bot's tools can read everything they need — done: 14 operations served from Postgres, the contract served as the document, and the drift test failing on a renamed field, a hidden route, a reused operation id, a changed bound, or an undeclared value. An adversarial review of the finished milestone drove eight fixes: routes are read from the router tree, parameter bounds are compared, the validator carries `minItems`, enums are checked by behaviour, the rule 3/4 scans use a whitelist and follow imports, freshness no longer calls a listed-but-empty competition fresh and ignores future-dated runs, and an out-of-range id is a 400 instead of a 500 |
| M3b | A test, not an opinion, on how questions get routed: two decision models run over the same questions and are scored on precision and recall against expectations we checked by hand | A results table, a decision written down, and a router that is right on the questions fans actually ask — **model chosen (2026-10-20)**: `clef:cloud` routed best and was signed off, with the cloud egress accepted; its refusal gap and the 0.90 target were the M4 gate, now measured (0.979 on v1, 0.960 on v2) |
| M4 | The bot on Telegram, with the first notes written and reviewed, and the routing the test chose | It answers the golden questions correctly, refuses when it should, every rules answer cites its note, and every note's sources are listed and checked in [`notes-sources.md`](notes-sources.md) — **done 2026-10-22**: routing gate measured at 0.979 gated macro-F1 on prompt v1 (0.960 on the v2 regression), MCP tools and Telegram gateway built, thirteen notes reviewed and indexed; the live Telegram smoke test needs the owner's bot token |
| M5 | Dashboard and scoreboard | Both tested, the scoreboard runs on every change, and it also scores where the bot looked |
| M6 | The pipeline that checks every change and can roll back a bad deploy, the monitoring and security paperwork, and the report on how AI was used | One alert that fires on real user impact, plus the audit paperwork, a record of what the agents did, and the final Mermaid pipeline diagram in `README.md` |

### M3b result (2026-10-19)

85 hand-labelled questions, 17 classes, 35 database / 35 notes / 15 gate; 34 dev + 51 holdout. The holdout was
written by an independent reviewer and audited by a second before freezing. Both models got the same versioned
request; the model was the only variable. Run `2026-10-19T12-40-46Z` (`evals/routing/results/`).

| Model | Dev acc | Holdout acc | Holdout macro P | Holdout macro R | Holdout macro F1 | p95 |
| --- | --- | --- | --- | --- | --- | --- |
| Model-1 `tev1:0.8b` (local) | 62% | 53% | 0.59 | 0.45 | 0.43 | 3.78 s |
| Model-2 `clef:cloud` (cloud) | 82% | **71%** | **0.78** | **0.79** | **0.70** | 1.60 s |

Safety gates, across all 85: tev1 refused **2/5** adversarial and **1/5** refusal; clef refused **5/5** and **3/5**.

| Route (holdout) | Support | tev1 P | tev1 R | clef P | clef R |
| --- | --- | --- | --- | --- | --- |
| tool | 21 | 0.62 | 0.86 | 0.93 | 0.62 |
| knowledge | 21 | 1.00 | 0.29 | 1.00 | 0.71 |
| clarify | 3 | 0.08 | 0.33 | 0.18 | 1.00 |
| refuse | 6 | 0.67 | 0.33 | 1.00 | 0.83 |

**What it means.** `clef:cloud` is the chosen router: 71% v 53% accuracy, macro-F1 0.70 v 0.43, and it refused all
five adversarial messages where tev1 refused two. It is a cloud model, so every Telegram message goes to Ollama's
cloud; the owner signed that off on 2026-10-20 as the cost of the better router. The local model is rejected:
knowledge recall 0.29 (it asks back or picks a tool for rules questions) and 2/5 adversarial refusals. clef still
refused only 3/5 of the refusal class and is 20 points short of the 0.90 macro-F1 target, so M4 adds a hard safety
gate around it. The full precision/recall tables, every choice and the egress note are in `evals/routing/results/`;
the reasoning is in [decision 0003](decisions/0003-prompt-router.md).

### M4 result (2026-10-22)

The routing gate was measured on a new independent holdout, not the archived sample: 60 questions written by
an independent reviewer and audited by a second, frozen at SHA-256 `c5236d8f…`, one run
(`evals/routing/results/2026-10-21T21-42-43Z`). Prompt v1 gated macro-F1 **0.979** against the 0.90 target;
adversarial 8/8, fabricated 4/4, refusal class 3/3 and unsupported 4/4 refused; zero false refusals and zero
database→notes errors. Raw pre-gate macro-F1 was 0.906. Prompt v2 adds the complexity question; the same frozen
holdout was re-run as a regression check (`2026-10-22T12-19-58Z`): gated macro-F1 **0.960**, all safety gates
still passed, one clarify question refused as `fabricated_fact`. The v2 run is a regression check, not a new
independent sample.

The rest of M4: eight read-only tools over MCP HTTP (`mcp_server/`), a Telegram gateway (`agent/gateway/`) whose
simple path uses one tool and the deterministic composer, whose complex path plans several tools or retrieves
several notes and composes with `beam:cloud`, and a citation verifier before sending. Thirteen reviewed notes in
English, each with a checked source URL (`_docs/notes-sources.md`), and 41 chunks in pgvector. The UCL
qualification note was corrected after review: domestic cups do not carry a Champions League place. The four
`unsupported` holdout questions predate the scorer tool: a scorer question now routes `tool` to
`get_top_scorers`, so those old labels are historical, not a current gate. The gateway records
every turn through the insert-only `agent_writer` role. The live Telegram smoke test is the owner's step after
creating a bot token; the same pipeline is exercised by `make ask` and the integration suite.

The notes themselves are written by hand and reviewed like code — see section 4. They are not fetched from anywhere and
the collection job does not go looking for them; it only re-indexes the ones that changed. They are written in English,
one topic per file, and each one is listed with its source in `hermes/agent-knowledge/manifest.yaml`; the build fails
if a note is not in the list or the list names a note that is not there.

Searching runs on a small model inside the local stack: `embeddinggemma:300m` turns text into 768 numbers per chunk,
so note text never leaves the machine and there is no per-question bill. Routing uses `clef:cloud`, the 27B model
that won the M3b comparison; its cloud call is the accepted egress path, and the decision is written down in
`_docs/decisions/`.

## 9. Still to decide

1. **Dashboard address:** settled as a **temporary tunnel, opened for the demo only** — no domain purchase and no
   permanent hostname, because nothing is meant to stay online after the recording. A permanent tunnel stays available
   as an option if the project ever needs a 24/7 dashboard, but then it also needs a machine that is never asleep.
2. **How much the dashboard can do:** read-only at first; any button that changes something (re-run collection) is
   admin-only and logged.
3. **Which model routes, and which holds the conversation:** routing is settled — `clef:cloud` (decision 0003),
   with the user message going to Ollama's cloud. The conversation model is configurable in Hermes but pinned for the
   scoreboard; the embedding model is fixed at `embeddinggemma:300m` (768 numbers per chunk).
4. **Licence:** the public repo currently has none chosen.
