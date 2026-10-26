# 0009 — M6: one branch, two commit groups, and the gaps that stay open

**Status:** accepted (2026-10-26)
**Milestone:** M6
**Related:** 0008 (dashboard and eval), 0010 (telemetry and alert egress), `_docs/product-spec.md` F10,
`_docs/follow-ups.md`

## Context

M6 is the last milestone: CI/CD, observability, alerting, on-call and the security artifacts. It was
planned as two pull requests (CI + security, then observability + on-call). The owner signed off the
whole scope and asked for the work on one branch with **no pull request until a manual local
inspection of the observability stack**, so the branch carries two commit groups rather than two
merged PRs.

The milestone also had to decide four questions that would otherwise drift: the ingest-trigger queue,
the eval-surfaced agent misses, the dashboard address and the licence.

## Decision

1. **One branch, two commit groups.** CI/security artifacts land first, then telemetry/observability/
   on-call, then the docs and the cleanup. The split is still visible in the history and in the
   review order; it is not a claim that the two halves carry the same risk.
2. **The ingest-trigger queue is deferred, with a design sketch.** Closing `POST /admin/ingest-runs`
   needs a queue table, a second narrow write role for the API, a scheduler that polls while waiting
   for its window, idempotency `(date, competition set)` and `409` semantics, and a contract decision
   (a queued request is not an `IngestRun`: either a `queued` status or a new response schema). That
   is product/API work, not operations work, and it would have required contract v0.5.0 in a security
   milestone. The operation stays a documented `404`; the owner string and the contract description
   now name the follow-up instead of M6. Design sketch: `_docs/follow-ups.md`.
3. **The eval-surfaced product misses are recorded follow-ups, not M6.** The name-resolver miss, the
   two `clarify` misses and the fabricated 2/3 are real; fixing them means prompt/model/resolver work
   and a new eval run. Mixing that into an operations change would make the scoreboard unreadable,
   and M6 changes no prompt, model or label.
4. **The dashboard stays local, with a demo-only tunnel.** No login, no permanent host. A permanent
   host is a separate decision with authentication, and it is out of scope here.
5. **No licence is chosen.** The repository is public without a licence, which is legally
   all-rights-reserved until the owner chooses one. That is the owner's decision, not an agent's; the
   reason is recorded in `_docs/scoping.md` §7 and `_docs/follow-ups.md`.
6. **One alert, evaluated locally.** `ingest_unhealthy` (stale / repeated failure / stuck run) is
   evaluated by `agent/oncall` against Postgres, with log + `alerts.json` + a Prometheus gauge as the
   destinations and owner Telegram as an opt-in extra (decision 0010).
7. **The eval stays a local gate.** CI never runs `make eval`: it sends the golden questions to
   `clef:cloud` and the router suite needs a signed-in host Ollama. The PR template records the local
   run; CI runs `--self-check`, which needs no model.

## Alternatives

- **Two PRs, merged in order.** The original plan and still the better shape for a normal review. The
  owner chose to inspect the stack before any PR; one branch keeps that inspection honest.
- **Close the ingest queue in M6.** Rejected for the contract and state-machine cost above.
- **Run the eval nightly in CI.** Rejected: a new cloud egress path for the golden questions and a
  signed-in model the runner does not have.
- **A Grafana alert rule instead of `oncall`.** Rejected: the alert would depend on the obs stack being
  up, and the source of truth is the ledger, which is reachable without Grafana.
- **A model-backed answer verifier on-call.** Rejected: a new egress path and a judge-validation
  study; the deterministic digest is enough for an operations signal.

## Consequences

- The milestone closes criteria 9–12 and leaves one documented API gap (the ingest trigger), one
  product-quality gap (three eval misses), no licence and no permanent dashboard host. Each is in
  `_docs/follow-ups.md` with the next step.
- The local-only nature of telemetry is a network fact for the four storage containers and an
  application-configuration fact for Grafana, which must also join the default network so its port can
  be published (decision 0010).
- The branch is pushed without a PR; the owner opens it after the manual inspection.

## Verification

`make test` (450), `make lint`, `make itest` (41), `make frontend-test` (27), `make e2e` (6),
`make eval-self-check`, `make security-scan`, the CI workflow via `actionlint` + the first run, the
alert drill in `ops/drills/2026-10-27-ingest-stale.md`, and the Docker cleanup report.
