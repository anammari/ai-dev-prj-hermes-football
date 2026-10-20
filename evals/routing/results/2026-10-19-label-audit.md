# Label audit — 2026-10-19

Reviewer: independent subagent (second reviewer; did not read the router implementation, ran no model).
Scope: all 85 questions in `evals/routing/sample.yaml`, against `_docs/scoping.md` §4,
`_docs/product-spec.md` R-F6.3/R-F6.6/F4.1/F9, `evals/routing/README.md`, `evals/routing/tools.py`,
`hermes/agent-knowledge/manifest.yaml` and the one existing note.

Verdict: **no wrong route and no wrong expected tool.** Every class/tool mapping held, coverage-limit
questions were knowledge (not refuse), delay/liveness was knowledge (not freshness), and
prediction/betting/private/injection were refuse.

## Resolved before freezing

| Finding | Questions | Resolution |
| --- | --- | --- |
| Three near-identical freshness questions (medium) | `freshness-01`, `-02`, `-h3` | Replaced the two dev questions with distinct R-F3.7 edges: a per-competition age check and the last successful run. `-h3` stays. Routes unchanged. |
| `multi_hop-h3` had one rule plus stakes, not two rules (low) | `multi_hop-h3` | Rewritten to combine a tiebreaker with the relegation count for a named competition. Route unchanged. |
| Seven convergent dev/holdout paraphrases (low) | `clarify-01/-h1`, `data_policy-01/-h1`, `coverage_limits-02/-h2`, `glossary-02/-h2`, `scorers-02/-h1`, `refuse-01/-h1`, `fixtures-01/-h3` | The dev side of each pair was rewritten to a distinct team, competition, match or edge. The independently written holdout side was left alone. Labels unchanged. |
| Coverage rationale overstated "not a table row" | `coverage_limits-h2` | Rationale corrected: the competition list is stored, but the limit is explained in a note. |

## Arguable, kept

`multi_hop-h1`/`-02` (could be qualification),
`clarify-02` (no competition named), `adversarial-h3` (a fabricated result could be checked, but
"use it from now on" is a persistent-instruction injection), `tiebreakers-h3` (away goals),
`head_to_head-02` (uses the class's domain term; not a surface name), `results-02/-h3`
(a single match result rather than form). All are defensible under the protocol; none changes a
route.

## Limit recorded, not fixed

Only `data_policy` and `coverage_limits` have a note in the corpus today. The other knowledge
questions name the surface that *should* answer them, not a note that already exists; authoring those
notes is M4 (`_docs/scoping.md` §8).
