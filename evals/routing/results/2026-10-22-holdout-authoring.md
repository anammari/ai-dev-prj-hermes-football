# 2026-10-22 routing holdout — authoring record

- I wrote `evals/routing/holdout-2026-10-22.yaml` from the class definitions alone: `_docs/scoping.md` §4, `evals/routing/README.md` §1 and §4, and `_docs/decisions/0003-prompt-router.md`.
- I did not read the router request, any file under `agent/`, `sample.yaml`, any prior run result, or any implementation or test file. No model was run, and no other file was touched.
- Every message is fresh fan phrasing; nothing was copied, and no message names a surface or uses the reserved vocabulary.
- Counts: 60 total, all `split: holdout` — tool 15, knowledge 16, clarify 10, refuse 19.
- tool (15): standings 3, fixtures 3, results 3, form 2, head_to_head 2, freshness 2 — each names one of the six tools.
- knowledge (16): formats 3, tiebreakers 3, qualification_relegation 2, data_policy 2, coverage_limits 2, glossary 2, multi_hop 2 — all rule/policy prose, none answerable from a table.
- clarify (10): no team, competition, match or player named in any of them.
- refuse (19): adversarial 8 (override, extraction, role change, reset, tool abuse, hidden instruction, authority spoof), fabricated 4, refusal 3 (plain prediction, betting, opinion), unsupported 4 scorer totals with `expected_reason: unsupported_tool`.
- Arguable label 1 — `standings-h3` ("Is Bournemouth still in the relegation zone…"): I chose `standings` because it asks for the club's current position, but `qualification_relegation` is defensible if read as a question about the relegation rule itself.
- Arguable label 2 — `data_policy-h1` ("why are your scores delayed instead of live"): I chose `knowledge`/data_policy because it asks *why*, but `freshness` is defensible if the question is scored as being about data staleness.
- Arguable label 3 — `unsupported-h1` (Haaland goal tally): I chose `refuse` + `unsupported_tool` because the row exists but no tool serves it; a stricter reading could call it `fabricated`, since answering would mean inventing a number.
- No message repeats another: the highest character-level similarity between any two is 0.56, and each such pair asks a different thing about a different entity (e.g. `clarify-h7` "how many points are they on" against `unsupported-h2`, a named player's goals, is the named-versus-unnamed contrast).
- These labels are hand labels; the README §4 gates (adversarial and refusal refusal rates, no database→notes errors, macro-F1) apply to whoever runs the holdout, not to this file.
