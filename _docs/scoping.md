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
| How delayed are the scores? | **Still unknown.** Every match that day was still upcoming, so we couldn't watch a delay happen. We measure it in M2 by watching one match until its score appears |

One more helpful detail: the API tells us how many calls we have left in the current minute, so we pace ourselves on
its own numbers instead of guessing.

## 4. When the database answers, and when our notes do

There are two ways to answer a football question, and mixing them up is how bots start making things up.

- **From the database** — the answer is a number, a date, or a table. The bot asks a tool, the tool runs a query, rows
  come back, the bot writes the sentence. Nothing needs to be "searched".
- **From our notes** — the answer is a sentence that someone wrote down: a rule, a format, a definition, or a policy
  of ours. Here the bot searches our own notes and answers from the passage it finds, citing where it came from.

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

## 6. Where it runs (and why not on Hugging Face)

Everything runs locally in Docker — the bot, the API, the database, the collector, the dashboard, the monitoring.
Nothing is installed on your machine except Docker itself.

The public part is the **Telegram bot itself**: Telegram works by the bot calling out to Telegram, so it needs no
incoming port, no static IP and no server. That is why "local only" and "a bot anyone can message" are not in
conflict.

For the dashboard we use a **free Cloudflare tunnel** — a public web address that points at the local stack. We also
have the option to publish the dashboard as a free static page on Hugging Face.

**Could Hugging Face Spaces host the whole thing for free? No.** Docker Spaces on free hardware now require a paid
plan (about $9/month), and even then one Space holds a single container — no database, no dashboard, no monitoring
alongside it. Its disk is wiped on restart, and free Spaces fall asleep after 48 hours of quiet, which for a Telegram
bot means a bot that stops answering. It is the wrong shape for this project, not just the wrong price.

## 7. How the 14 course criteria are covered

Each row is a requirement from the course's draft project criteria and the thing in this repo that satisfies it.

| # | Course requirement | How this project meets it | Where to look |
| --- | --- | --- | --- |
| 1 | Problem description | README and spec explain what the bot answers, what the free data allows, and what it says when it doesn't know | `README.md`, `_docs/product-spec.md` |
| 2 | How AI was used | A versioned collection of the prompts used, written project instructions for AI helpers, and a log of what was delegated, reviewed and rejected | `prompts/`, `AGENTS.md`, `_docs/ai-usage-report.md` |
| 3 | Technologies and architecture | A diagram and a short explanation of every part, and why it is there | `_docs/architecture.md` |
| 4 | Front end | The dashboard, with its own tests and clear instructions to run them | `frontend/`, `tests/e2e/` |
| 5 | API contract | The API is written down first in `openapi.yaml`, the backend follows it, and a test fails if they drift apart | `openapi.yaml` |
| 6 | Back end | Layered FastAPI code with tests on the important endpoints | `backend/` |
| 7 | Database | Works with a simple file database in development and Postgres in the full stack, with migrations and a documented schema | `db/`, `_docs/data-model.md` |
| 8 | Containerisation | One `make up` starts everything; health checks included | `docker-compose.yml`, `Makefile` |
| 9 | Integration testing | Tests that run against the real stack, from collection to a bot reply — kept separate from the unit tests | `tests/integration/` |
| 10 | Deployment | A public Telegram bot plus a public dashboard address, with a check after each deploy | `_docs/deployment.md` |
| 11 | CI/CD | Every pull request runs lint, tests and the answer-quality scoreboard; merging to main deploys, verifies and can roll back | `.github/workflows/` |
| 12 | Agent extension pack | Project instructions, a reusable routine, a checker helper, our own tool server, a guardrail, and a written list of what the bot may do | `skills/`, `subagents/`, `mcp-server/`, `hooks/`, `docs/permissions.md` |
| 13 | Security, audit and ops | An AI code-review on pull requests, scanner findings, a capability list for the bot, an incident rehearsal, and a written data policy | `security/`, `ops/`, `observability/` |
| 14 | Reproducibility | Three commands from a clean machine: set up, start, test end to end | `README.md`, `Makefile` |

## 8. The plan

| Step | What it means | Done when |
| --- | --- | --- |
| M0 | Empty repo, scope, spec, API contract | Done |
| M1 | Database schema and the first migration, matching the contract | Tests against the real stack pass |
| M2 | Daily collection from the football API | A day's data lands with a run log, and the real score delay is measured |
| M3 | The wrapped API | The bot's tools can read everything they need |
| M4 | The bot on Telegram | It answers the golden questions correctly, and refuses when it should |
| M5 | Dashboard and scoreboard | Both tested, and the scoreboard runs on every change |
| M6 | Automation, monitoring, security | One alert that fires on real user impact, plus the audit paperwork |

## 9. Still to decide

1. **Dashboard address:** a permanent Cloudflare tunnel (needs a domain you own) or a temporary one whose address
   changes on restart. Default: temporary first, permanent before the final submission.
2. **How much the dashboard can do:** read-only at first; any button that changes something (re-run collection) is
   admin-only and logged.
3. **Which AI model:** configurable in Hermes, but pinned for the scoreboard so scores stay comparable.
4. **Licence:** the public repo currently has none chosen.
