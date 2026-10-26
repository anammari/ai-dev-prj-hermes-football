# AI usage report — Hermes Football

Course criterion 2. What was delegated to agents, what a human reviewed, what was rejected, and what proves it.
Entries are added with the work they describe.

## How to add an entry

- **Delegated:** what the agent was asked to produce, and which agent.
- **Reviewed:** what a human read and what changed.
- **Rejected or revised:** what an agent proposed and a human threw out or corrected, and why. Empty is a smell.
- **Evidence:** test, scan, lint, commit or artifact that shows it holds.

## Sessions

**S1 — Align M1 wording (2026-10-10).** Agent reconciled `scoping.md` and `product-spec.md`; human set the tie rule
(newest statement wins). Agent first called the documents merely differently worded; inspection showed the spec
credited M0 work to M1. Evidence: both docs and `AGENTS.md` agree.

**S2 — Scope corpus, embedding and router (2026-10-10).** Agent answered three open questions. Human corrected a model
tag claim after supplying the vendor page; agent verified 768-d and fixed the record. Agent proposed deterministic
routing; human required an experiment instead, which became the M3b comparison. Evidence: decisions 0001–0003.

**S3 — M6 scope and MCP transport (2026-10-10).** Agent scoped later operations work and chose MCP over HTTP. Human
accepted the split. Evidence: product spec F10, architecture.

**S4 — Schema, corpus and embedder (2026-10-10).** Agent built migration `0001`, manifest, chunker and embedding
client; human reviewed. Rejected: generating notes at runtime. Evidence: one note indexed and retrieved; tests.

**S5 — Ingestion pipeline (2026-10-11).** Agent built client, rate limiter, bronze store, loaders and ledger. Review
found the run could fail on one optional sub-resource; fixed to record and continue. Evidence: live run, 13
competitions, ~9.9k matches.

**S6 — Ingestion close-out (2026-10-12).** Agent added README index, score-delay tool and the derived Ollama image.
Human rejected keeping the 7 GB upstream image in use; the CPU-only build replaced it. Evidence: decision 0005.

**S7 — Copilot review of ingestion (2026-10-13).** Sixteen findings, fourteen applied; two explicitly rejected with
reasons. Evidence: commits, tests, review notes.

**S8 — Backend API (2026-10-13).** Agent built 14 read-only operations against the contract, read-only role and drift
tests. Adversarial review produced cases for a hidden route, reused operationId, changed bound and undeclared enum.
Evidence: `backend/`, contract tests.

**S9 — Router comparison (2026-10-19).** Two model-first routers, same 85 questions. `clef:cloud` beat `tev1:0.8b`
(71% v 53% accuracy, macro-F1 0.70 v 0.43). Human signed off cloud egress; selected clef. Evidence: `evals/routing/`.

**S10 — Source URL table (2026-10-21).** Agent compiled checked URLs for the planned notes. Human required a separate
`notes-sources.md`, not URLs in the manifest. Rejected aggregators as sources; clean sheet has no official definition;
provider page contradicts the probe. Evidence: 20 URLs checked, all 200/206.

**S11 — Routing gate, MCP and Telegram (2026-10-22).** Agent built prompt v2, gate, turn writer, eight MCP tools,
Telegram gateway, 13 notes/41 chunks. Two independent agents authored/audited the 60-question holdout; gated macro-F1
0.979, all safety gates. Evidence: result artifact, 358 unit + 38 integration tests.

**S12 — Complexity and Beam (2026-10-22).** Owner rejected the deterministic-only answer layer. Agent added
`simple`/`complex`, planner, `beam:cloud` composer and fallback. Owner signed off complex-path egress. Prompt v2
regression: 0.960. Evidence: `tests/test_complex_path.py`, live `make ask`.

**S13 — Scorer gap closed (2026-10-23).** Investigation showed 5,583 scorer rows already stored; the gap was the
missing API/tool, not paid data. Agent added contract v0.3.0 endpoint, MCP tool and player lookup. Rejected direct DB
access and defaulting to the Premier League. Evidence: live endpoint, Haaland answer.

**S14 — PR review: verifier and token (2026-10-23).** Copilot review arrived before the no-review-request rule. Agent
fixed the weak citation-only verifier with a second model claim check, passed `MCP_SERVER_TOKEN` to the gateway, and
fixed a `TeamForm` crash. Evidence: tests, live complex answer.

**S15 — Six High findings (2026-10-23).** Fixed one-pass prompt substitution, hidden SQL parameters, no owner DB
credentials in MCP/gateway, MCP token propagation, errored routing counted as a miss, and the UCL cup-route note.
Also short club names, argument errors, off-loop MCP handling, SOUL egress wording, freshness label, timestamp check,
test host mapping, isolated MCP start and test auth. Evidence: 358 unit, 38 integration, lint; live checks.

**S16 — Dashboard, eval scoreboard and the first honest score (2026-10-25).** One session on
`anammari-m5-dashboard-evals`, one PR. Delegated: an **independent author** wrote the 48-question golden set from the
product definition, the manifest and the notes only (blinders: no implementation, no prompts, no prior results); a
second **independent auditor** then reviewed every label against the same sources and found no wrong route, no invented
heading, two duplicate pairs, and a set of term groups that would have failed *correct* answers. The author applied the
audit in two more rounds. The agent wrote the contract revision (v0.4.0, two eval reads + the review write), migration
0004, the eval harness, the dashboard (seven routes, one `server-only` client), the Compose/CI-less test plumbing and
these docs.

What the run found, and what was changed rather than hidden:
- the first live eval scored routing macro-F1 0.928 but the scoreboard went red: fact coverage 0.67 and five missing
  citations. The misses were split into (a) label defects - value-based terms that fail a correct answer, fixed by
  making tool terms entity-only - and (b) real product misses, kept red: `inter milan vs juventus` is not resolved by
  the name resolver, three answerable questions routed `clarify`, and one fabricated-fact question asked back instead
  of refusing.
- the freshness composer did not name its source; rule 2 applies to the freshness answer too, so it now says
  `source: hermes-football ingestion ledger` and a test pins it.
- the eval itself recorded a tool failure as a clean answer at first; it now records `tool_unavailable` and counts it
  as an error, so a contended machine looks contended instead of incompetent.
- a knowledge search takes 9-11 s on this machine (local CPU embedding); two of 48 questions hit the 20 s MCP timeout
  under load. `MCP_TIMEOUT_SECONDS` is now documented in `.env.example` as the knob, and the finding is recorded.
- harness author's one label correction: `la liga` gained the provider's own name `primera division` as an alias,
  after the live run showed the composer printing it. No route, tool, note or heading label was changed by the harness
  author; every other label change came from the author after the audit.

Rejected: a model judge (new egress, judge-validation study), a browser-side API client (token in every visitor's
bundle), a general admin write engine (rule 4 would stop being a grant), and tuning the first run green.

Evidence: `tests/test_golden_set.py`, `tests/test_eval_metrics.py`, `tests/test_eval_runner.py`,
`tests/test_eval_store.py`, `tests/test_evals_api.py`, `tests/integration/test_admin_review_stack.py`, 26 Vitest
tests, 6 Playwright specs, migration 0004, contract v0.4.0, and the stored run in `eval_runs` with its artifact under
`evals/golden/runs/`.

## Rejected or revised, in one place

- Deterministic routing, regex, or a second model to paraphrase answers: rejected by the owner and rule 10.
- Generating the notes at runtime: rejected; notes are hand-written and reviewed.
- Keeping the 7 GB upstream Ollama image: replaced by the 637 MB CPU-only build.
- Reusing the archived 85-question sample for the new gate: rejected; a new independent holdout was frozen.
- Answering scorer questions from the nearest table: rejected; the gap is now closed with a real endpoint/tool.
- Sending simple answers to `beam:cloud`: rejected; only complex answers leave the machine.
- Requesting Copilot reviews from an agent: now forbidden in `CLAUDE.md`; the owner decides.

## Sessions that predate this log (backfill needed)

The early scaffold, scoping and contract commits predate this report. The backfill list is in the git history; the
decisions and specs carry the substance.

## Where prompts live

[`prompts/`](../prompts/README.md): `0001` backend task, `0002` router comparison, `0003` production router, `0004`
complex planner, `0005` complex composer, `0006` claim verifier. Each is versioned with the behaviour it shapes.
M5 adds **no new prompt**: its scoring is deterministic, so there is no judge prompt to version (decision 0008).
