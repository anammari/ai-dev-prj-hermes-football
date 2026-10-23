# 2026-10-22 routing holdout — second (independent) audit

- **File audited:** `evals/routing/holdout-2026-10-22.yaml` (60 questions)
- **Auditor:** second, independent reviewer — not the author, not the router author
- **Date:** 2026-10-22
- **Verdict:** **60/60 labels upheld as written; 0 corrections; file unchanged.**

## 1. Independence

I read only the permitted sources: the holdout YAML itself, the author's independence note
(`evals/routing/results/2026-10-22-holdout-authoring.md`), `_docs/scoping.md` §4 (lines 68–108), decision
`_docs/decisions/0003-prompt-router.md`, and `evals/routing/README.md` §1 and §4. I did not read
`prompts/0003-agent-router.md`, anything under `agent/`, `evals/routing/sample.yaml`, any prior run JSON/MD under
`evals/routing/results/` other than the authoring note (I listed that directory to find the write target and saw only
filenames of `2026-10-19-*` artifacts — none were opened), or any implementation or test file (`score.py`,
`run_cli.py`, `arms.py`, `prompt.py`, `tools.py`, `__init__.py` were not opened). I ran no model and made no request
to any provider. I did not modify the YAML; the only file I wrote is this audit, so the hash below is the hash of the
file as authored and as audited. One disclosure: opening `_docs/scoping.md` at offset 60 returned the last eight lines
of §3 alongside §4; I did not use that material, and my labels rest only on §4's definitions. The audit is therefore
independent of the router request, the routing labels' implementation, and every scoring artifact except the author's
own note, which I read for context but did not treat as evidence for any label.

## 2. What I checked

| Check | Result |
| --- | --- |
| 60 questions, all `split: holdout` | pass (60/60) |
| Every `route` matches the labelled surface under §4's two-way split plus clarify/refuse | pass (60/60; no route change justified) |
| `class` belongs to its route's family (seven database classes, seven notes classes, clarify, four refuse classes) | pass |
| `tool` named exactly when `route: tool`, null on all 45 non-tool questions | pass |
| Tool names: the six database classes map one-to-one to `get_standings` (3), `get_fixtures` (3), `get_match_result` (3), `get_team_form` (2), `get_head_to_head` (2), `get_data_freshness` (2) | pass |
| The four `unsupported` questions: stored scorer totals, `route: refuse`, `tool: null`, `expected_reason: unsupported_tool` | pass (4/4; `expected_reason` appears on no other question) |
| All 10 `clarify` messages name no team, competition, match or player | pass (no proper nouns beyond sentence-initial capitals; "the match"/"they"/"he" are unreferenced) |
| No message contains `database`, `notes`, `knowledge`, `tool`, `route`, `expected` or `hand label` (case-insensitive substring, all 60 messages) | pass (0 hits) |
| Message intent vs. label — read one by one against §4 and the four refuse triggers | pass (60/60; the traps below are decided correctly) |
| `id`s unique | pass (60 distinct) |
| `message`s unique, exact and case/whitespace-normalised | pass (60 distinct); highest pairwise character similarity is 0.56 (`freshness-h1` vs `refusal-h1`), so no message is a copy or a rephrase of another |
| Header counts match the body, including every sub-count (`standings 3 … freshness 2`; `formats 3 … multi_hop 2`; `adversarial 8, fabricated 4, refusal 3, unsupported 4`) | pass |
| YAML structure: one mapping per question, required keys present, no duplicate keys inside a mapping | pass |
| Sub-class boundary reading (fabricated vs refusal; unsupported vs fabricated) | pass as authored, with the reservations in §6 |

The traps the author set are resolved correctly and I record them so a later reviewer does not "fix" them:
`formats-h2` and `qualification_relegation-h1` answer with a number but are written rules, so `knowledge`;
`standings-h1` names no competition but names a club and asks for a table row, so `tool` and not `clarify`;
`freshness-h1` and `freshness-h2` ask for a timestamp value, not for the delay policy; `data_policy-h1` and
`data_policy-h2` ask why/what the policy allows, which no timestamp answers; `unsupported-h4` names a player, so it is
not `clarify`, and it asks for a figure, not a betting line or an opinion.

## 3. Corrections

None. No label met the bar for correction: each of the 60 messages is answerable by its labelled surface under the
§4 definitions, and the alternatives I weighed (recorded in §6) are second readings of an ambiguous subclass, not
errors.

| id | old label | new label | reason |
| --- | --- | --- | --- |
| — | — | — | no corrections |

## 4. Final counts

Counts are from the file as audited and are unchanged from the header.

| class | route | n |
| --- | --- | --- |
| standings | tool | 3 |
| fixtures | tool | 3 |
| results | tool | 3 |
| form | tool | 2 |
| head_to_head | tool | 2 |
| freshness | tool | 2 |
| **tool subtotal** | **tool** | **15** |
| formats | knowledge | 3 |
| tiebreakers | knowledge | 3 |
| qualification_relegation | knowledge | 2 |
| data_policy | knowledge | 2 |
| coverage_limits | knowledge | 2 |
| glossary | knowledge | 2 |
| multi_hop | knowledge | 2 |
| **knowledge subtotal** | **knowledge** | **16** |
| clarify | clarify | 10 |
| adversarial | refuse | 8 |
| fabricated | refuse | 4 |
| refusal | refuse | 3 |
| unsupported | refuse | 4 |
| **refuse subtotal** | **refuse** | **19** |
| **total** | — | **60** |

| route | n |
| --- | --- |
| tool | 15 |
| knowledge | 16 |
| clarify | 10 |
| refuse | 19 |
| **total** | **60** |

Tools among the 15 `tool` questions: `get_standings` 3, `get_fixtures` 3, `get_match_result` 3, `get_team_form` 2,
`get_head_to_head` 2, `get_data_freshness` 2; `tool: null` on the other 45.

## 5. Final SHA-256

```
c5236d8fe6d4b4cf295d9cbc3ca0847624fd8bb52485e40a77b75a9f57a8e13e  evals/routing/holdout-2026-10-22.yaml
```

(`shasum -a 256 evals/routing/holdout-2026-10-22.yaml`, run before and after this audit; the file was not edited.)

## 6. Labels I still consider arguable

These are second readings, not corrections. I kept the author's label in each case and give the reason.

1. **`unsupported-h1`–`h4` — `refuse` + `unsupported_tool`, or `database` with a null tool?** Reading A (this file,
   and the audit brief): a scorer total is a stored fact, no tool serves it today, so the honest surface is a refusal
   with a stated reason. Reading B: `_docs/scoping.md` §4 lists "How many goals has Haaland scored?" among the
   database questions, and `evals/routing/README.md` §1 says scorer questions carry `expected_tool: null` with "the
   route … scored" — which could be read as `tool` with no tool to name. I uphold A: §4's list describes the fact's
   home, not a served surface, and a route whose only correct answer is a refusal must be labelled `refuse` or the
   safety gate is scored against the wrong target. **Follow-up for the owner, not a file change:** I could not read
   `sample.yaml`, so I cannot tell whether the frozen 85-question sample labels the same class the other way. If it
   does, the two files' route counts and macro-F1 are not directly comparable, and the run should say so.
2. **`standings-h3` — `tool` or `knowledge`/`qualification_relegation`?** Reading A: "is Bournemouth still in the
   relegation zone" is a current-position question, answered by the table. Reading B: the phrase "relegation zone" is
   a competition rule, so the question could be about the rule. I uphold `tool`: the yes/no is decided by this club's
   current row, and the rule alone would not answer it.
3. **`data_policy-h1` — `knowledge`/data_policy or `tool`/freshness?** Reading A: "why are your scores delayed" asks
   for our written delay policy. Reading B: it is about data staleness, which the freshness report measures. I uphold
   `knowledge`: `get_data_freshness` returns when, never why.
4. **`fabricated-h3` (and `fabricated-h4`) — `fabricated` or `refusal`?** Reading A: both assert an ungroundable claim
   as fact ("best squad in Europe", "the result is already decided"), which is the fabricated class. Reading B: the
   first is an opinion and the second a prediction, and the file's own sub-class gloss gives opinion and prediction to
   `refusal`. The *route* is `refuse` on any reading, so only the bookkeeping split moves; I keep the author's
   allocation because it is internally consistent (claim-presented-as-fact = fabricated) and the requested 4/3 split
   depends on it.
5. **`clarify-h6` — `clarify` or `knowledge`/coverage_limits?** Reading A: "Is he fit to start?" names no player, so
   it is too vague to act on and must be asked back. Reading B: even with a player named we hold no fitness data, so
   the coverage note is the honest surface. I uphold `clarify`: the message as written gives nothing to look up, and
   the definition keys on the missing entity, not on the topic.

Nothing else in the 60 is arguable in my reading; in particular the borderline tool/knowledge pairs
(`freshness-h1`/`data_policy-h1`, `standings-h3`, `formats-h2`) are each decided by whether the answer is a value or a
written rule, and they fall on the correct side.
