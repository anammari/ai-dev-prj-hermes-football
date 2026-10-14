# 0001-m3-backend-api.md — build the M3 API against `openapi.yaml`

```yaml
version: 1
used by: M3 (backend/, tests/test_api_*.py, tests/integration/test_backend_stack.py, docker-compose.yml)
model: deepseek-v4.1-flash (DeepSeek Harness coding agent), single agent, root checkout
date: 2026-10-13
owner: Ahmad Ammari
status: reviewed — the plan was approved before any code was written, and the result was reviewed against the
        acceptance criteria below
```

The prompt is recorded here because the task shaped product behaviour: it decided the error semantics of the public
API, the shape of the freshness report, and what the drift test covers. It is reproduced as given, minus the local
paths and the environment details that carry no meaning for a reviewer.

## The task, as given

> Kick off M3: the backend API in `/Users/ahmadammari/GitHub/ai-dev-prj-hermes-football`. Repo on `main` with M2
> merged. Read first, in order: `AGENTS.md` (hard rules) → `_docs/scoping.md` §7 row 6 + §8 → `_docs/product-spec.md`
> §F3 + §7 → `openapi.yaml` (source of truth) → `_docs/data-model.md`, `db/models.py`, `db/session.py` →
> `_docs/ai-usage-report.md` "How to add an entry". Build `backend/` (FastAPI) against the contract; it does not
> exist. Criterion 6 is worth points and asks for it, and criterion 5 expects a test that fails when the backend
> drifts from `openapi.yaml`. Change the contract only in the same PR as the behaviour that needs it. Leave the
> router alone — `_docs/decisions/0003` requires the M3b spike's numbers before it is written. Work in one small PR
> on a branch off main, and show me your plan before writing code.

## Binding constraints the plan had to satisfy

1. `openapi.yaml` is the only definition of a response shape. The API may not publish a document generated from its
   own code, or the drift test would be checking the implementation against itself.
2. `AGENTS.md` rule 3: no upstream access from request-handling code. The API holds no provider credential and no HTTP
   client, and a static test enforces that.
3. `AGENTS.md` rule 4: the agent's data path is read-only. One engine, logged in as `agent_readonly` where the
   deployment has that role; no write engine exists.
4. `AGENTS.md` rule 10: every turn says which road it took, so the turn log serves `route`, `route_source` and
   `route_confidence` — which is why the contract gained them (v0.1.0 → v0.2.0) in this same change.
5. Admin scope: read-only, with the two write operations declared and answered with a contract-shaped 404 naming the
   milestone that implements them.
6. The contract's own vocabulary for missing data: 503 `data_not_available` is "not in the database *yet*" and must
   never be reported as "no matches"; 404 is "no such resource"; an empty filter result is a 200 with an empty list.

## Acceptance criteria the work was checked against

- Every operation in `openapi.yaml` is either implemented or on a declared list, and a test forbids that list from
  containing anything the contract marks as an agent tool.
- A renamed, removed or non-nullable response field makes a test fail; a route the contract does not declare, or a
  documented route with no operation, makes a test fail; parameter names and requiredness are compared both ways.
- The validator used by the sweep is itself tested: a deliberately drifted payload must be rejected.
- `/openapi.yaml` returns the repository file byte for byte, `/docs` renders that file, `/openapi.json` is a 404.
- Freshness is attached to every answer, and `/meta/freshness` derives the whole picture from the run ledger —
  including the case that a run which lists no competitions refreshes nothing.
- Every token-protected operation answers 401 without a valid bearer token, with no token in the response body, and an
  unconfigured token refuses everything rather than opening the API.
- `make test` is green on SQLite, `make lint` is clean, and the integration suite repeats the contract sweep on
  Postgres with the read-only role.

## What the reviewer changed

The plan was approved with four amendments, all of which are in the code: the read-only admin scope, leaving the
router out, keeping the contract change in the same commit, and treating the drift test as a deliverable. The
implementation review then corrected two contract descriptions that the stored data contradicts, and one response
field that was duplicated rather than referenced. Those are logged in
[`_docs/ai-usage-report.md`](../_docs/ai-usage-report.md) session S8, which is where a reviewer should look for what
was rejected rather than applied.
