# 0003 — How the bot chooses between the database and the notes (router spike)

- **Status:** Proposed — the implementation is chosen by the spike below; this record moves to Accepted with the result
- **Milestone:** M3b (spike), M4 (implementation), M5 (scoring)
- **Related:** `_docs/product-spec.md` R-F6.3, R-F6.6, F9; `_docs/scoping.md` §4, §8

## Context

`R-F6.3` states the rule — structured questions from SQL, qualitative ones from retrieval, and never retrieval for
something the database answers correctly — and `_docs/scoping.md` §4 gives the one-line version. What was missing was
the mechanism: today the choice is whatever the chat model picks from the MCP tool schema, steered only by `SOUL.md`.
That is unmeasurable, and it is exactly where the two documented failure modes live: searching documents for a score,
and querying a database for the meaning of "aggregate".

## Options

| | Option | Summary |
| --- | --- | --- |
| A | Deterministic-first | Code maps the shape of the question to an intent bucket; a model is consulted only when the shape is ambiguous |
| B | Model-first | A small decision model routes every prompt before any tool runs |
| C | Status quo | The chat model's native tool selection: no router, logged but unscored (baseline) |

Laya is the candidate for option B: a 421M decision model (ModernBERT-large backbone) from Convai, no text generation,
Apache-2.0, `POST /v1/systemone`, `choice`/`noul`/`score` questions, a 512-token budget per question, English-only,
requires Ollama ≥ 0.40.0. Its vendor numbers — 99.1% in-task routing, 65.1% zero-shot on held-out task families — were
measured on someone else's distribution, so they are a reason to test it, not a reason to trust it.

## Decision

**Run the spike before writing the router.** No option is adopted on intuition.

1. **Sample.** 60–100 prompts covering the seven question classes of `_docs/scoping.md` §4, plus unanswerable and
   adversarial (prompt-injection) cases. Each carries a hand-reviewed ground-truth label — *structured tool* or
   *knowledge* — with the expected tool name where one applies.
2. **Arms.** A, B and C over the same sample, against the same tool surface from M3.
3. **Judge.** An LLM-as-judge scores whether the route taken was correct for the question and the available tools. The
   judge prompt is versioned in `prompts/`. Every disagreement, plus a random sample of agreements, is reviewed by
   hand, and the judge–human agreement rate is reported: a judge that is not itself checked is just another opinion.
4. **Metrics.** Routing accuracy per class; the direction of each error (retrieval used for a factual score is the
   worst case); added latency p95 against the ~10 s budget; refusal behaviour preserved.
5. **Output.** A results table in `_docs/scoping.md` §8 and an accepted decision in this record: the winning arm, the
   confidence threshold if a model is used, and the intent labels the router chooses from.

Whatever the outcome, these hold:

- The route is **recorded on every turn** (`agent_turns.route`, `route_source`, `route_confidence`) and scored in the
  eval harness, so it cannot regress unnoticed.
- The router sees the user's message and a fixed label set — **never retrieved text, never tool output**.
- Counting, date arithmetic and comparisons stay in code; a model is only ever asked whether a stated condition holds.
- The tool surface stays read-only and allowlisted; the router cannot widen a query.

## Consequences

- M4 cannot start its routing work before the spike finishes, so the plan carries it as its own row (M3b).
- The router reuses the `ollama` container and capability row introduced by 0002 for embeddings.
- Option B adds one model call per message; the spike has to show it earns that cost against the latency target.

## Verification

- The spike report: sample size, per-class accuracy, judge–human agreement, latency, chosen threshold.
- M5: routing accuracy is a scored eval dimension, and a deliberately wrong route is caught by the harness.
