# Follow-ups — recorded, not hidden

Everything here is deliberately outside its milestone. A follow-up is not a maybe: it names the gap,
the evidence, and the next step.

## Product quality (from the M5 eval run)

The newest live run (`evals/golden/runs/1f812eaf-…json`) is red on purpose: macro-F1 0.928, retrieval
0.906, fact coverage 0.858, three answers without a citation. The real misses:

1. **Name resolver: `inter milan vs juventus`.** The resolver does not map "inter milan" to the stored
   club; the question is answerable from `get_head_to_head`. Next step: extend the alias table and add
   the case to the routing sample; do not soften the label.
2. **Two answerable questions routed `clarify`.** The router asks back on questions the corpus/data can
   answer. Next step: a prompt revision with a targeted regression set, then a holdout run; the
   scoreboard keeps one series per set.
3. **One fabricated-fact question asked back (fabricated 2/3).** The safety gate did not convert it to
   a refusal. Next step: an adversarial case in the holdout and a prompt revision; the gate itself is
   one pass and must not become a regex list (decision 0006).

Fixing these changes prompts or the resolver, so it is its own milestone with a new eval run. M6
changed neither, which is why the stored history is still readable.

## Ingest-trigger queue — `POST /admin/ingest-runs`

The operation is a documented `404` (contract v0.4.1). Closing it needs:

- a queue table (request id, requested_at, competitions, force, status, run_id) and a narrow
  `agent_ingest_requester` role with INSERT only — a second API write, against the spirit of rule 4,
  so it needs its own capability row and a test naming the columns;
- a scheduler restructure: the `ingest` process currently sleeps until its window and cannot poll;
  claiming needs `SELECT … FOR UPDATE SKIP LOCKED` (Postgres) and a SQLite fallback;
- idempotency per `(date, competition set)` and a `409` when a run is in progress;
- a contract decision: the `202` currently returns an `IngestRun`, but a queued request is not yet a
  run. Either add a `queued` status (contract + schema + dashboard) or a new `IngestRequest` schema —
  contract v0.5.0;
- a dashboard re-run button and the incident-runbook link.

Until then the dashboard does not offer the button and the runbook uses `make ingest`.

## Deployment and access

- **Dashboard login.** There is no authentication; the Cloudflare tunnel is demo-only. A permanent host
  needs a login, an owner decision on the host, and a security review (the tunnel is the only boundary
  today).
- **Permanent hostname.** Depends on a machine that never sleeps; out of scope while the project runs
  on a laptop.
- **Licence.** No licence is chosen; the repository is all-rights-reserved by default. The owner picks
  one (MIT is the obvious candidate) before any reuse or distribution.
- **GitHub branch protection.** `main` is unprotected; the owner should require the CI `ci` aggregate
  (and the individual jobs it summarises) before merging.

## Platform

- **Multi-turn memory.** Each message routes alone; `clarify` resolves one question, not a
  conversation.
- **Embedding latency.** A knowledge search takes 13–18.5 s on this machine (the cause of the M6
  timeout fix). Investigate quantisation/threads or a smaller model; the timeout budget is a safety
  net, not a UX fix.
- **Weekly eval automation.** The on-call agent reports `eval_age_days` but does not run the eval,
  because that would send the golden questions to `clef:cloud` on a schedule. Automating it needs an
  owner egress decision and a fresh-set strategy.
- **Model-backed answer verifier.** Would need a new egress path and a judge-validation set; the
  deterministic checks stay.
- **Optional Nous Hermes Agent deployment.** `hermes/config.yaml` records the surface; the shipped
  gateway is `agent/gateway` (decision 0007).
- **Image scanning on every push.** `trivy image` runs on main/nightly, not on every PR, for time.
- **Actions pinned by SHA.** Dependabot keeps the tags current; a hardening pass can pin every action
  to a commit SHA.
