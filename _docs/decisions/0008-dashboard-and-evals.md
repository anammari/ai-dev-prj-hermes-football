# 0008 — The dashboard is server-rendered, and eval scores are deterministic

**Status:** accepted (2026-10-25)
**Milestone:** M5
**Related:** 0003 (routing model and its egress), 0006 (safety gate), 0007 (Telegram gateway and the complex-path
egress), `_docs/product-spec.md` F7/F9, `_docs/rag.md` §6

## Context

M5 needed three things the earlier milestones did not: a human-readable surface, a way to score the agent over time,
and a single write so a human can mark an answer right or wrong. Each had an obvious bigger version that would have
cost policy, egress or scope:

- an SPA that calls the API from the browser, which means shipping `API_AGENT_TOKEN` to every visitor;
- a model judge for relevance, faithfulness and completeness, which means a new cloud path and a judge-validation
  study;
- a general admin API with a write engine, which would make the "agent data path is read-only" rule a matter of
  discipline rather than a grant.

## Decision

**1. The dashboard renders on the server and holds the tokens.** `frontend/` is a Next.js App-Router app; every page
is `force-dynamic` and fetches inside the server process through one typed client generated from `openapi.yaml`. The
client imports `server-only`, so an accidental client import fails the build. The e2e suite asserts that no served
chunk contains the agent or admin token and that the browser makes no request off the dashboard origin. The dashboard
is exposed locally on `:3000`; a tunnel is demo-only and is stopped after a demo.

**2. The one write is the review decision, and it is narrower than a write engine.** `PATCH
/admin/agent-turns/{id}/review` uses `API_ADMIN_TOKEN` and the `agent_admin` role, whose grant is UPDATE on
`review_status` and `review_note` and nothing else. Empty admin token means `403` disabled, not an open door. The
agent token cannot call it. `POST /admin/ingest-runs` stays a documented `404` until the queue exists, because a request handler
must not start an upstream run (rule 3) and the trigger needs a queue the ingest container drains.

**3. Eval scores are deterministic, and there is no model judge.** The golden set carries expected routes, tools,
notes, headings and machine-checkable term groups; the runner scores routing, retrieval, citation coverage and fact
coverage with plain arithmetic, and stores the evidence so anyone can recompute a run. A judge would have needed its
own hand-labelled validation and a new egress decision, and neither was signed off for M5. The consequence is stated
rather than hidden: "completeness" means the required terms are present, not that the prose is good.

**4. A run is stored in Postgres and as a file.** `eval_runs`/`eval_results` make the scoreboard queryable;
`evals/golden/runs/<id>.json` is the reproducible artifact. A run names its set and the set's hash, because a score on
a different sample is a different series, and the dashboard draws one line per set hash.

## Alternatives

- **Client-side dashboard with the agent token in the browser.** Rejected: the token would be readable by anyone who
  can reach the tunnel, and the API would be one copy-paste from public.
- **A model judge for relevance/faithfulness.** Rejected for M5: it adds an egress path and a validation obligation,
  and the deterministic metrics already catch the failures that matter (wrong road, wrong note, missing fact, missing
  citation). Revisit only with an owner sign-off and a hand-labelled judge-validation set.
- **A general admin write engine.** Rejected: rule 4 survives because the grant is per column, not because a reviewer
  promises the code is careful.
- **Keeping eval results only as files.** Rejected: the scoreboard needs to filter and compare runs, and a growing
  directory is not a queryable history. The file stays as the artifact, not as the store.

## Consequences

- The dashboard cannot be a public product without a login; that is deliberate, and the tunnel is demo-only.
- A page that shows a number must show its provenance; the API's `meta` block is the only source of that timestamp.
- The eval's numbers are conservative: a correct answer that omits a required term scores lower. The term groups are
  therefore limited to entities for data questions and rule keywords for notes, and the first live run's misses are
  recorded rather than tuned away.
- `agent_turns` keeps the public bot's real traffic; eval questions are not written there.

## Verification

`tests/test_api_security.py` (only `backend/services/reviews.py` may write, and only the two review columns),
`tests/integration/test_admin_review_stack.py` (the column grant on real Postgres), `frontend/e2e/security.spec.ts`
(no token in a browser, no request off-origin), `tests/test_golden_set.py`, `tests/test_eval_metrics.py`,
`evals/golden/runner.py --self-check`, and the stored first run in `eval_runs`.

## Update (M6, 2026-10-26)

The ingest trigger is still a documented `404`. Closing it was deferred out of M6 because it needs a queue the
scheduler drains, a second narrow write role and a contract-visible queue state (a queued request is not yet an
`IngestRun`). The decision, the design sketch and the owner string are in
[`0009`](0009-m6-operations.md) and [`../follow-ups.md`](../follow-ups.md). Nothing else in this record changed.
