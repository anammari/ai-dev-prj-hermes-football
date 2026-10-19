# Hermes Football

A Telegram bot that answers football questions **accurately** — from a local database refreshed every day from
football-data.org, plus a small hand-written set of notes about the rules, which the bot searches rather than guesses
from ([how that works, and how it is scored](_docs/rag.md)). When the data does not support an answer, it says so
instead of guessing. Everything runs on your own machine in Docker; there is no server to rent.

Status: **M1–M3b comparison done.** Two model-first routers were compared on the same 85 hand-labelled questions:
`clef:cloud` beat `tev1:0.8b` on accuracy and precision/recall, but neither passed the safety gates, and clef sends
messages to a cloud provider. No router is adopted yet; **M4** owns that choice — see the
[milestone tracker](#milestone-tracker) at the end.

## How to read this README

One short section per course criterion, in the order they are assessed. Every section starts with its status, so a
marker can walk the list from top to bottom and see at a glance what is done:

- **Implemented** — built and verified.
- **In Progress** — started, with the missing part named in the section and the milestone that brings it.
- **Not Started** — nothing in the repository yet.

The numbers below are **criterion numbers, not milestones** (milestones are M0–M6). The full mapping is
[`_docs/scoping.md`](_docs/scoping.md) §7.

## 1. Problem Description

- **Implemented** — written down in M0 and kept current.
- Football answers are easy to find and often wrong: scores arrive late, tables go stale, and a confident model will
  invent both.
- This bot answers questions about fixtures, results, standings and competition rules from the free football-data.org
  API plus a small hand-written corpus, and it puts the data's own timestamp on every answer.
- When the data cannot support an answer — a question it cannot ground, a competition the free plan does not cover, a
  match that has not been played — it says so rather than guessing.
- Predictions, betting tips and live scores are out of scope on purpose.
- More detail: [`_docs/scoping.md`](_docs/scoping.md) in plain language, [`_docs/product-spec.md`](_docs/product-spec.md)
  as requirements.

## 2. AI-Assisted Development Workflow

- **Implemented** — all three artefacts exist and are updated with every milestone.
- [`prompts/`](prompts/README.md) — the prompts used while building, versioned like code so they can be reviewed
  instead of staying in a chat window.
- [`AGENTS.md`](AGENTS.md) — the instructions every AI assistant reads first, including ten hard rules: ground your
  answers, show freshness, respect the ten-requests-per-minute budget, keep the agent's data path read-only, never put
  a secret in a prompt.
- [`_docs/ai-usage-report.md`](_docs/ai-usage-report.md) — what was delegated to an agent, what a human reviewed, what
  was rejected and why, and which test proves it. Session S8 covers M3, including the eight findings an adversarial
  review turned up after the milestone looked finished.

## 3. Technologies and System Architecture

- **Implemented** — the diagram, the stack and the standing decisions are written down.
- The picture: Telegram → `hermes` (the agent) → `mcp-server` → `backend` → PostgreSQL, with `ingest` refilling the
  database daily and `ollama` serving the model locally so no question leaves the machine.
- The notes half runs the same way: the Markdown files in [`hermes/agent-knowledge/`](hermes/agent-knowledge/manifest.yaml)
  are chunked and embedded by the local model into pgvector, and the bot looks a passage up through
  `GET /search/knowledge` instead of asking a model to remember the rules. No RAG framework in between — the task
  prefixes and the vector width are two named constants in our own code, which is
  [explained in `_docs/rag.md`](_docs/rag.md) §3.
- Diagram and stack: [`AGENTS.md`](AGENTS.md) §Architecture. Plain language:
  [`_docs/scoping.md`](_docs/scoping.md) §1, with "why not a rented GPU" in §6.
- Decisions are recorded as they are made, in [`_docs/decisions/`](_docs/decisions/README.md) — the notes corpus, the
  embedding model, routing decisions, the container embedding.
- A dedicated `_docs/architecture.md` arrives with **M6**; until then `AGENTS.md` is the source of truth.

## 4. Frontend Implementation

- **Not Started** — arrives with **M5**.
- The dashboard (data freshness, fixtures and standings, the agent log, eval results, admin controls) is specified in
  [`_docs/product-spec.md`](_docs/product-spec.md).
- It will be a Next.js/TypeScript app with one typed API client, Vitest unit tests and Playwright end-to-end tests.
- The eval view will separate retrieval failures from answering failures rather than showing one accuracy number —
  context relevance, context recall, faithfulness and completeness, with the diagnosis each combination implies. The
  proposal is [`_docs/rag.md`](_docs/rag.md) §5.
- Neither `frontend/` nor `tests/e2e/` exists yet.

## 5. API Contract

- **Implemented** in **M3** — [`openapi.yaml`](openapi.yaml) is the source of truth for what the API serves, written
  before the code.
- The running API serves that file **verbatim** at `/openapi.yaml`, and `/docs` renders it, so anyone can compare the
  live API with this repository. FastAPI's own generated document is switched off, so there is no second version of
  the truth to drift.
- Tests read the file and fail if the code drifts: an undeclared route, a documented operation with no route, a renamed
  or removed field, a changed parameter name, bound or default, a reused operation id, or a version bump on one side
  only — see [`tests/test_api_contract.py`](tests/test_api_contract.py).
- The checker is proved to work, not assumed: one test deliberately breaks a response and expects the check to fail.
  That is how the gaps listed in the S8 entry were found and closed.
- The contract changes only together with the behaviour that needs it: v0.2.0 added the routing fields rule 10 asks for,
  and the size limit on ids, in the same commit as the code that uses them.

## 6. Backend Implementation

- **Implemented** in **M3** — [`backend/`](backend) is a FastAPI service that answers the fourteen read-only
  operations in the contract.
- It reads PostgreSQL as the read-only role `agent_readonly`, holds no write path and no upstream credential, and every
  agent-facing endpoint needs a bearer token (`API_AGENT_TOKEN`). With no token configured it refuses everything
  instead of opening up.
- The two admin writes are declared but answer a 404 naming the milestone that owns them (**M5**): a documented gap
  beats a silent one.
- Freshness is part of every answer: the provider's own `lastUpdated` for matches, the snapshot time for tables, and a
  `/meta/freshness` report that never calls a competition fresh when the database holds no rows for it.
- "We have no data" is not "not found": a competition nobody ingested answers `503`, a missing season or snapshot
  answers `404`, and a filter that matches nothing answers `200` with an empty list.
- One directory per concern — routers validate and shape, services run the queries, `schemas.py` maps rows to the
  contract, `contract.py` reads the enums from the file.
- Try it: `make up`, then <http://localhost:8000/docs>. Tests:
  [`tests/test_api_endpoints.py`](tests/test_api_endpoints.py),
  [`tests/test_api_insights.py`](tests/test_api_insights.py),
  [`tests/test_api_freshness.py`](tests/test_api_freshness.py),
  [`tests/test_api_security.py`](tests/test_api_security.py).

## 7. Database Integration

- **Implemented** — PostgreSQL 16 with pgvector in the stack, SQLite for development, on one code path, with
  migrations applied on startup.
- Tables: [`db/models.py`](db/models.py), created by the migrations in
  [`db/migrations/versions/`](db/migrations/versions/0001_init.py). How each table maps onto the contract, and what is
  still open: [`_docs/data-model.md`](_docs/data-model.md).
- The notes corpus is stored as 768-number vectors with a similarity index behind them, so the bot can find the note
  that answers a question about the rules.
- The API only ever reads, through a role that cannot write: [criterion 13](#13-security-audit-and-devops-hardening)
  explains how that is enforced.

## 8. Containerization

- **Implemented** — one `make up` starts everything that exists today: `db`, `ollama`, the `backend` API and the daily
  `ingest` scheduler, migrations included. Later components join as their milestones land.
- [`docker-compose.yml`](docker-compose.yml) defines the services, volumes and health checks; the
  [`Makefile`](Makefile) is the only entry point; secrets come from `.env` at run time and are never baked into an
  image.
- Start-up order is gated on health: the API waits for the database and the model server to report healthy.
- The API is the only service with a published port, and it is given no upstream key and no Docker socket. That is
  asserted by a test, not just intended.
- The model server is a derived image: stock Ollama is 7.05 GB, most of it CUDA libraries that cannot load on Apple
  Silicon. Ours is **637 MB** — [decision 0005](_docs/decisions/0005-ollama-image.md).

## 9. Integration Testing

- **Implemented** — [`tests/integration/`](tests/integration) holds the tests that need the real thing: PostgreSQL
  with pgvector, the local embedding model, the read-only role, the running API.
- `make test` runs the fast unit tests on SQLite; `make itest` runs these against the running stack;
  `make itest-isolated` runs them against a throwaway stack when the retained data must not be touched.
- The stack suite repeats the contract sweep using ids read from the real volume, and proves the API's database role
  cannot write.
- They are kept out of the fast run on purpose, and they never write to the retained database.

## 10. Deployment

- **Not Started** — arrives with **M6**.
- The bot itself is the public interface, using long polling so nothing has to be exposed inbound; the dashboard will
  be reachable through a Cloudflare tunnel.
- Public access is switched on for **one short recorded demo** and shut down afterwards: the laptop is the server for
  those minutes only, and no tunnel, hostname or session outlives the recording. The demo video is the evidence; the
  always-on alternative is deliberately not the plan.
- `_docs/deployment.md` will record the addresses and the check that runs after each deploy.
- No VPS and no cloud host, on purpose — the reasoning is in [`_docs/scoping.md`](_docs/scoping.md) §6.

## 11. CI/CD Pipeline

- **Not Started** — arrives with **M6**.
- `.github/workflows/` will lint, run both test suites and score answer quality on every pull request; merging to
  `main` will deploy, verify and be able to roll back.
- Until then the same checks run locally, and [criterion 14](#14-reproducibility) lists them.

## 12. Agent Extension Pack

- **In Progress** — the instructions and the first notes exist; the rest of the pack arrives with **M4–M6**.
- Already here: [`AGENTS.md`](AGENTS.md) — the instructions and rules every assistant reads first — and the first
  hand-written note, the data policy at
  [`policy/free-tier-delay-and-coverage.md`](hermes/agent-knowledge/policy/free-tier-delay-and-coverage.md), listed with
  its source in [`manifest.yaml`](hermes/agent-knowledge/manifest.yaml).
- The rest of the corpus — competition formats, tiebreakers, a glossary — is written and reviewed in **M4**, where the
  bot starts answering questions about the rules.
- Still to come: reusable skills, the `answer-verifier` subagent, the read-only MCP tool server, hooks and guardrails.
  `skills/`, `subagents/`, `mcp-server/` and `hooks/` do not exist yet.
- Every capability gets a line in `docs/permissions.md` before it ships — an undocumented capability is not shippable
  (rule 8).

## 13. Security, Audit, and DevOps Hardening

- **In Progress** — the rules are already enforced in code and tests; the paperwork and the monitoring arrive with
  **M6**.
- Enforced today, by the hard rules in [`AGENTS.md`](AGENTS.md) and the tests that check them: a read-only database role
  for everything the agent can reach, no Docker socket in a container, secrets never in the repository or in a prompt,
  Telegram input treated as untrusted, and no capability left undeclared.
- Written today and quotable by the bot itself:
  [`free-tier-delay-and-coverage.md`](hermes/agent-knowledge/policy/free-tier-delay-and-coverage.md) — the data policy
  that explains the delay and the coverage limits instead of hiding them.
- Still to come (**M6**): `security/` scanner findings and the capability and threat tables, `ops/` runbooks and an
  incident rehearsal, `observability/` with one alert that fires on real user impact, and an AI code review on pull
  requests.

## 14. Reproducibility

- **Implemented** — three commands take a clean machine to a working stack, after one edit: put your free
  football-data.org key into `.env`.

```bash
make setup     # create .env from .env.example, build the app image
# add your free football-data.org token as UPSTREAM_API_KEY in .env
make up        # start db and ollama, pull the model, migrate, start the API and the scheduler
make test      # unit tests
```

- The API is then on <http://localhost:8000> (`/docs` for the interactive contract). Its bearer token is
  `API_AGENT_TOKEN` in `.env`; an empty one is not an open door — the app refuses every agent-facing request and says
  why in the log.
- `make setup` copies `.env.example`, whose key is a placeholder, and the collector refuses to start on a placeholder
  rather than failing hours later. On a fresh `ollama` volume, `make up` also pulls the pinned embedding model.
- Nothing else is installed on the host: Docker, this repository and a `.env`.

| Command | What it does |
| --- | --- |
| `make up` / `make down` | Start the stack (db, model server, API, scheduler) and apply migrations / stop everything |
| `make test` / `make itest` | Fast unit tests / the same suite against the running stack |
| `make itest-isolated` | Those tests against a throwaway stack, for when the retained data must stay untouched |
| `make ingest` | One manual collection run (needs a real key in `.env`) |
| `make score-delay [MATCH_ID=…]` | Report how old the provider's data for one match is right now |
| `make lint` / `make validate-spec` | Ruff over the repository / lint the API contract |
| `make logs S=db` | Tail one service's logs |

Every other target — migrations, model pull, corpus checks, search, Swagger — is listed with a one-line description in
the [`Makefile`](Makefile).

If a build complains that buildx cannot write its state directory (a locked-down machine), prefix it with
`DOCKER_BUILDKIT=0`.

## Milestone tracker

| M# | Item | Stage |
| --- | --- | --- |
| M0 | Empty repo, scope, product spec, API contract | Done |
| M1 | Database schema and first migration, notes table with vectors, corpus manifest and local embedding | Done |
| M2 | Daily collection from football-data.org: run ledger, idempotent loads, re-indexing changed notes | Done |
| M3 | Backend API against `openapi.yaml`: fourteen read-only operations, read-only role, freshness report, drift test | Done |
| M3b | Router comparison: `tev1:0.8b` (local) versus `clef:cloud`, scored on precision/recall against hand-checked expectations | Done — clef routed best; no model adopted, safety and egress gates failed |
| M4 | Telegram agent: `SOUL.md`, first notes reviewed, routing model choice and gate fixes, refusal and freshness behaviour | **Next** |
| M5 | Dashboard and eval scoreboard, including routing accuracy | Later |
| M6 | CI/CD, observability, security, deployment and the AI-usage report | Later |

**M3b compared two models, and neither can ship yet.** `clef:cloud` routed better than the local `tev1:0.8b`:
71% v 53% accuracy, macro-F1 0.70 v 0.43, and it refused all five adversarial messages. But clef sends every
message to Ollama's cloud, against the local-inference rule, and refused only 3/5 of the refusal class; the local
model refused 2/5 adversarial messages. **No model is adopted.** The numbers and per-route precision/recall are in
[`_docs/scoping.md`](_docs/scoping.md) §8, the reasoning in
[decision 0003](_docs/decisions/0003-prompt-router.md), and every choice in `evals/routing/results/`.

Each milestone's meaning and "done when" are stated in two places: [`_docs/scoping.md`](_docs/scoping.md) §8 in plain
language, and [`_docs/product-spec.md`](_docs/product-spec.md) §8 as requirements.

## Project documents

- [`_docs/scoping.md`](_docs/scoping.md) — start here: what we are building, what the free API actually allows, and how
  the fourteen course criteria are covered
- [`_docs/product-spec.md`](_docs/product-spec.md) — requirements, acceptance criteria, data model
- [`_docs/data-model.md`](_docs/data-model.md) — the tables, how they map onto the contract, and what is still open
- [`_docs/rag.md`](_docs/rag.md) — the notes the bot can search: how they are chunked, embedded and stored, what is
  built versus owed, and how retrieval quality will be measured
- [`openapi.yaml`](openapi.yaml) — the API contract, written before the code
- [`_docs/decisions/`](_docs/decisions/README.md) — standing decisions: notes corpus, embedding model, router
- [`AGENTS.md`](AGENTS.md) — durable context and the hard rules for anyone, or anything, working here
- [`_docs/ai-usage-report.md`](_docs/ai-usage-report.md) — what was delegated to agents, and what a human caught
- [`prompts/`](prompts/README.md) — the versioned prompt bank
