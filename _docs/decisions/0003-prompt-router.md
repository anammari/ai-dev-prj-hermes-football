# 0003 — Which model routes a question between the database and the notes

- **Status:** Proposed (2026-10-19) — the comparison chose `clef:cloud` on quality, but **no router is adopted**:
  clef fails the refusal gate and carries a cloud-egress blocker, and `tev1:0.8b` fails safety and quality. This
  record moves to Accepted when a model passes the gates in M4.
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
6. **Egress is a gate of its own.** `clef:cloud` cannot be adopted while `_docs/product-spec.md` §4 says inference
   stays local and no user question goes to a hosted provider. A quality win does not change that policy.

Whatever the outcome: the route is recorded on every turn (`route`, `route_source`, `route_confidence`), the
router sees the user message and a fixed label set only, and the tool surface stays read-only and allowlisted.

## Outcome (2026-10-19)

Run `evals/routing/results/2026-10-19T12-40-46Z` (report `.md` beside it). Prompt v1, same 85 questions, both
models on Ollama 0.40.6, no errors on either side.

| Model | Dev acc | Holdout acc | Holdout macro P | Holdout macro R | Holdout macro F1 | Adversarial (85) | Refusal (85) | p95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Model-1 `tev1:0.8b` | 62% | 53% | 0.59 | 0.45 | 0.43 | **2/5** | **1/5** | 3.78 s |
| Model-2 `clef:cloud` | 82% | **71%** | **0.78** | **0.79** | **0.70** | **5/5** | **3/5** | 1.60 s |

Holdout per-route precision / recall:

| Route | Support | tev1 P | tev1 R | clef P | clef R |
| --- | --- | --- | --- | --- | --- |
| tool | 21 | 0.62 | 0.86 | 0.93 | 0.62 |
| knowledge | 21 | 1.00 | 0.29 | 1.00 | 0.71 |
| clarify | 3 | 0.08 | 0.33 | 0.18 | 1.00 |
| refuse | 6 | 0.67 | 0.33 | 1.00 | 0.83 |

**The comparison has a winner and no adoption.**

1. **`clef:cloud` routes better on every headline metric.** 71% v 53% accuracy, macro-F1 0.70 v 0.43, macro recall
   0.79 v 0.45, and it refused all five adversarial messages where tev1 refused two. Its weakness is `clarify`:
   precision 0.18, so it asks back too often, and it refused only 3/5 of the refusal class.
2. **`tev1:0.8b` is not viable.** It sends most rules questions to `clarify` or to a tool (knowledge recall 0.29),
   refuses 2/5 adversarial messages, and is slower on CPU (3.78 s p95).
3. **Neither passes the gates.** clef fails the refusal class (3/5) and the cloud-egress gate; tev1 fails both
   safety gates. No model is adopted. The best model is recorded, not shipped.
4. **The 0.90 macro-F1 target is not met.** clef is 20 points short on holdout. The next milestone must either
   find a local model that clears the gates or change the data policy explicitly; a cloud win is not a licence to
   send Telegram messages to a provider.

**What M4 does with this.** The router stays model-first. The candidate is a model that passes safety on a new
independent holdout; `clef:cloud` is the quality reference, not the deployment. If the owner decides the local-only
rule can change, that is a separate recorded decision, not this spike's side effect. The missing scorer tool
(`R-F4.1`) and the incomplete corpus remain open and are recorded elsewhere.

**Limits.** The cloud arm uses synthetic eval messages, not user conversations; adopting it would change that.
The sample is single-turn, so `clarify` means vague as a standalone message. Both models share one prompt, so a
prompt tuned for one would invalidate the comparison. The sample's knowledge labels are taxonomy-correct while
only two of the seven knowledge classes have a note today.

## Verification

- `make router-spike` reproduces the run; `make test` and `make lint` cover the sample, prompt loader, arm
  plumbing and precision/recall arithmetic without calling a model.
- The run artifact holds every choice, timing, model digest, prompt version, sample hash and the egress note.
