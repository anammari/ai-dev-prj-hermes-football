# 0003 — Which model routes a question between the database and the notes

- **Status:** Accepted (2026-10-20) — **`clef:cloud` is selected as the routing model**, with its cloud egress signed
  off. Selection is not production adoption: the model failed the all-85 refusal gate (3/5), so M4 must add and pass a
  hard safety gate before the router is wired. The local `tev1:0.8b` is rejected.
- **Milestone:** M3b (comparison, done), M4 (implementation and gate fixes), M5 (scoring)
- **Related:** `_docs/product-spec.md` R-F6.3, R-F6.6, F9; `_docs/scoping.md` §4, §8; `evals/routing/README.md`

## Context

Routing is model-first: every message goes to a decision model before any tool runs. There is no deterministic
pre-router and no regex. The open question is **which model**, measured on the same hand-labelled sample, with the
same request and the same label definitions. The two candidates differ in size, runtime, cost and — for one of
them — whether the message leaves the machine.

## Options

| | Model | What it is | Where it runs | Egress |
| --- | --- | --- | --- | --- |
| 1 | `tev1:0.8b` | 0.8B decision model from Together AI, Qwen3.5 backbone, typed choices | spike-only Ollama 0.40.6 container | local only |
| 2 | `clef:cloud` | 27B decision model from Cloudflare, Qwen3.8 backbone, typed choices | signed-in Ollama on the host, reached from the test container | **every message goes to Ollama's cloud** |

Both answer the same `choice` request (`prompts/0002-router-model-comparison.md`): a surface
(`database`/`notes`/`clarify`/`refuse`) and, in the same forward pass, a tool. The contract maps `database` to
`tool` and `notes` to `knowledge`; `clarify` and `refuse` keep their names.

## Decision

**Run the comparison before any router is written.** No model is adopted on intuition, vendor numbers or size.

1. **Sample.** 85 hand-labelled questions, 17 classes × 5: 35 database, 35 notes, 15 gate (clarify, refuse,
   adversarial); 34 dev + 51 independent holdout. The sample and its splits are frozen
   (`evals/routing/sample.yaml`, SHA-256 in every run). The holdout was written by an independent reviewer and
   audited by a second before freezing.
2. **Arms.** Model-1 and Model-2 over the same request and the same questions. The model is the only variable.
3. **Metrics.** Per-route **precision and recall** on the holdout, macro precision/recall/F1, accuracy, full
   accuracy where a tool is named, tool precision/recall, adversarial and refusal gates, latency p95, and model
   errors.
4. **No judge.** The hand labels decide. A model does not grade another model; `R-F9.2` applies only if a judge is
   introduced later.
5. **Gates.** Adoptable only with adversarial 5/5 refused, refusal class 5/5 refused, zero database→notes errors,
   and no model errors. Higher holdout macro-F1 wins; ties go to recall, then lower p95. `0.90` macro-F1 is the
   target.
6. **Egress is recorded, then decided by the owner.** `clef:cloud` sends each message to Ollama's cloud. The
   comparison reports it; the owner signs it off or rejects the model. On 2026-10-20 the owner signed it off, and
   `_docs/product-spec.md` §4 was updated to say which data leaves the machine and why.

Whatever the outcome: the route is recorded on every turn (`route`, `route_source`, `route_confidence`), the
router sees the user message and a fixed label set only, and the tool surface stays read-only and allowlisted.

## Outcome (2026-10-19)

Run `evals/routing/results/2026-10-19T12-40-46Z` (report `.md` beside it). Prompt v1, same 85 questions, both
models on Ollama 0.40.6, no errors on either side.

| Model | Dev acc | Holdout acc | Holdout macro P | Holdout macro R | Holdout macro F1 | p95 |
| --- | --- | --- | --- | --- | --- | --- |
| Model-1 `tev1:0.8b` | 62% | 53% | 0.59 | 0.45 | 0.43 | 3.78 s |
| Model-2 `clef:cloud` | 82% | **71%** | **0.78** | **0.79** | **0.70** | 1.60 s |

Safety gates, across all 85 (the holdout has only 3 adversarial and 3 refusal questions):

| Model | Adversarial | Refusal |
| --- | --- | --- |
| Model-1 `tev1:0.8b` | 2/5 | 1/5 |
| Model-2 `clef:cloud` | 5/5 | 3/5 |

Holdout per-route precision / recall:

| Route | Support | tev1 P | tev1 R | clef P | clef R |
| --- | --- | --- | --- | --- | --- |
| tool | 21 | 0.62 | 0.86 | 0.93 | 0.62 |
| knowledge | 21 | 1.00 | 0.29 | 1.00 | 0.71 |
| clarify | 3 | 0.08 | 0.33 | 0.18 | 1.00 |
| refuse | 6 | 0.67 | 0.33 | 1.00 | 0.83 |

**`clef:cloud` is selected; production wiring waits for the M4 safety gate.**

1. **It routes better on every headline metric.** 71% v 53% accuracy, macro-F1 0.70 v 0.43, macro recall 0.79 v
   0.45; on the holdout it refused all three adversarial messages where tev1 refused one. Its weakness is `clarify`:
   precision 0.18, so it asks back too often, and across all 85 it refused only 3/5 of the refusal class.
2. **`tev1:0.8b` is rejected.** It sends most rules questions to `clarify` or to a tool (knowledge recall 0.29),
   refuses 2/5 adversarial messages, and is slower on CPU (3.78 s p95).
3. **The egress sign-off is explicit.** clef runs in Ollama's cloud, so each Telegram message goes to a hosted
   provider. The owner signed this off on 2026-10-20 as the cost of the better router. The product spec now says so;
   the 85 spike messages were synthetic eval text, but production messages are real user input.
4. **Safety remains M4 work.** clef refused 3/5 of the refusal class, so the model alone is not the safety layer: M4
   needs a hard pre-routing refusal for instruction overrides and fabricated facts, re-measured on a new independent
   holdout. The 0.90 macro-F1 target is still 20 points away. Selection is an owner exception to rule 5, not a claim
   that the gate passed.

**What M4 does with this.** Add the safety gate around `clef:cloud`, keep the route recorded on every turn, and close
the scorer tool gap (`R-F4.1`). Production wiring happens after that gate, not before. The local-only rule is no longer
a blocker for routing; it still applies to note retrieval and embeddings.

**Limits.** The comparison used synthetic eval text; production messages will leave the machine. The sample is
single-turn, so `clarify` means vague as a standalone message. Both models shared one prompt, so a prompt tuned for
one would have invalidated the comparison. The sample's knowledge labels are taxonomy-correct while only two of the
seven knowledge classes have a note today.

## Verification

- The run artifact is retained; the spike server and `tev1` were removed after the decision, so a rerun needs both
  models pulled again. `make test` and `make lint` cover the sample, prompt loader, arm plumbing and
  precision/recall arithmetic without calling a model.
- The run artifact holds every choice, timing, model digest, prompt version, sample hash and the egress note.

## M4 outcome (2026-10-22)

The gate this record asked for is implemented in [decision 0006](0006-routing-safety-gate.md) and measured on a
new independent 60-question holdout: gated macro-F1 0.979, adversarial 8/8, fabricated 4/4, refusal class 3/3,
unsupported 4/4, zero false refusals. Prompt v2 adds the complexity question; the same frozen holdout re-run as a
regression check scored 0.960 gated macro-F1 with all safety gates still passed (`2026-10-22T12-19-58Z`). The
independent v1 run is `2026-10-21T21-42-43Z` in `evals/routing/results/`. The comparison above
is unchanged; the production request adds the safety question, so its scores are not compared as if the request
were identical.
