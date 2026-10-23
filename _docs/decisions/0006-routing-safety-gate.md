# 0006 — The routing safety gate: one pass, a binding answer, no regex

- **Status:** Accepted (2026-10-22)
- **Milestone:** M4
- **Related:** `_docs/decisions/0003-prompt-router.md`, `_docs/product-spec.md` R-F6.6, `prompts/0003-agent-router.md`, `evals/routing/results/2026-10-21T21-42-43Z.md`

## Context

Decision 0003 selected `clef:cloud` but recorded a refusal gap: the model refused only 3/5 of the
refusal class, so the model alone was not the safety layer. M4 also has to enforce two hard rules:
the router sees the user message and a fixed label set only, and there is no regex or deterministic
pre-router. The gate therefore cannot inspect the message itself, and it cannot be a second
deterministic decision layer.

## Options

1. **A deterministic deny-list before the router.** Rejected: rule 10 removes regex and deterministic
   pre-routing, and a phrase list is exactly the brittleness the M3b comparison was meant to replace.
2. **A post-answer verifier only.** Not enough for this job: by the time an answer exists, a tool has
   already run. The verifier (planned for M4/M6) checks grounding, not intent.
3. **A separate safety-model call before the router.** Rejected: it doubles the cloud egress and the
   latency, and the same model supplies both judgements, so it buys no independence.
4. **A third `safety` choice in the routing pass, applied as a hard veto.** Chosen.

## Decision

`prompts/0003-agent-router.md` asks the model for `surface`, `tool` and `safety` in one forward pass.
`safety` has three labels: `safe`, `instruction_override`, `fabricated_fact`.

The application is deterministic and can only downgrade:

- any `safety` label other than `safe` becomes `route: refuse`, with the safety confidence and the
  label as the reason; the surface choice cannot override it;
- `surface: database` with `tool: not_applicable` becomes `refuse`, reason `unsupported_tool` (the
  scorer gap, refused rather than answered from the wrong table);
- a model or transport failure becomes `refuse`, `route_source: fallback`, no confidence;
- otherwise the surface mapping stands.

The gate runs before any tool or note is touched. The decision model is still the only judge of
content; the gate is the hard application of the model's own answer. `route_source` is `model` for a
model-made decision (including a gated refusal) and `fallback` only when no model answer exists.

## Consequences

- A false `fabricated_fact` or `instruction_override` costs an answerable turn. The holdout measured
  zero false refusals on 31 answerable questions, so the trade is acceptable; it is re-measured when
  the prompt or model changes.
- The gate cannot catch a wrong `safe` label. That remains a routing-quality question, not a safety
  one, and the holdout scores it separately.
- `route_source: rules` remains in the contract for compatibility but is never produced.

## Verification

- The frozen 60-question holdout, authored and audited independently: prompt v1 gated macro-F1 0.979, 8/8
  adversarial, 4/4 fabricated, 3/3 refusal, 4/4 unsupported, zero false refusals, zero database→notes errors
  (`evals/routing/results/2026-10-21T21-42-43Z.md`). Prompt v2 adds the complexity label; the regression run
  scored 0.960 with all safety gates still passed (`2026-10-22T12-19-58Z`).
- Unit truth table in `tests/test_agent_router.py`; the outbound body is asserted to carry only the
  model, the message and the label sets.
- Integration: `tests/integration/test_gateway_stack.py` sends an override, a scorer question and a
  vague question through the real router and asserts the route and the absence of a tool call.
