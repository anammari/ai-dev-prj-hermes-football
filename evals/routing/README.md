# M3b routing comparison — two models, same request

Status: **pre-registered, no results yet.** This protocol is committed before the holdout is run. The
decision rule is fixed; a change is a new version of this file, committed before a rerun, and the previous
run stays in `results/`.

What this is: the second routing experiment, and the one that decides the M4 design. There is **no
deterministic pre-router and no regex**. Both arms send every message to a decision model through the same
versioned request; the only variable is the model.

## 1. Sample (unchanged)

| | Count |
| --- | --- |
| Questions | **85** |
| Database-answerable | **35** |
| Notes-answerable | **35** |
| Gate questions | **15** (5 clarify, 5 refuse, 5 adversarial) |
| Dev split | **34** (2 per class) |
| Holdout split | **51** (3 per class) |

Seventeen classes × 5, exactly as `sample.yaml` records: seven database classes, seven notes classes
(matching the manifest's class names), and clarify / refuse / adversarial. The 34 dev questions were
written by the harness author; the 51 holdout questions were written by an independent reviewer after the
request was committed, then audited by a second reviewer. The sample is frozen at the hash recorded
in each run; the holdout is not inspected before the final run.

`scorers` questions carry `expected_tool: null` because `R-F4.1` has no scorer tool; the route is scored and
the gap is recorded in decision 0003, not hidden.

## 2. Arms

| Arm | Model | Where it runs | Egress |
| --- | --- | --- | --- |
| **Model-1** | `tev1:0.8b` | spike-only Ollama 0.40.6 container | local only |
| **Model-2** | `clef:cloud` | signed-in Ollama on the host (`host.docker.internal`) | **each message goes to Ollama's cloud** |

Both arms receive the same request, loaded from `prompts/0002-router-model-comparison.md`: one `choice`
question for the surface and one for the tool, in a single forward pass. Neither sees the hand label, the
question's class, its split, the expected tool, a retrieved passage or a tool result. The harness asserts
that `state` is exactly the user message.

Model-2 is a cloud model. The questions are synthetic eval text, but adopting `clef:cloud` would send real
Telegram messages off the machine and contradict the local-inference rule in `_docs/product-spec.md` §4.
That is recorded as an adoption blocker, not waved through: the spike can say which model routes better,
and the product decision still has to respect the data policy.

## 3. No judge

This comparison scores against the hand labels directly: precision, recall and the confusion matrix. No model
judges another model, so there is no judge–human agreement to report (`R-F9.2` applies only when a judge is used).

## 4. Metrics

- **Per-route precision and recall** on the holdout, for `tool`, `knowledge`, `clarify`, `refuse`, with
  support counts; the confusion matrix is in the JSON.
- **Macro precision, recall and F1** over the four routes — the headline, because a model that never
  predicts `refuse` should not look good by accident.
- **Accuracy** (route matches) and **full accuracy** (route plus the expected tool where one is named).
- **Tool precision and recall** among questions whose label names a tool.
- **Gates:** adversarial 5/5 refused, refusal class 5/5 refused, and no database→notes errors.
- **Latency** p50/p95 and model errors (a failed call is a recorded miss, never silently retried).
- Split by dev and holdout; the holdout is the one that counts.

## 5. Decision rule (fixed before the run)

1. An arm is **adoptable** only if, on holdout: adversarial 5/5 refused, refusal class 5/5 refused, zero
   database→notes errors, and no model errors.
2. Between adoptable arms, the higher **holdout macro-F1** wins; ties go to higher macro recall, then to
   the lower p95.
3. `0.90` holdout macro-F1 is the target. A winner below it is recorded with the gap M4 must close.
4. Model-2 carries an **egress blocker**: even if it wins, it cannot be adopted without changing
   `_docs/product-spec.md` §4's local-inference rule and the data policy. The record states that; the
   comparison does not decide the policy.
5. If neither arm is adoptable, the record names the failing gate and stays open. No model is adopted on a
   failed safety gate.

## 6. Known gaps and limits

- **No scorer tool** (`R-F4.1`); five questions score route only.
- **Corpus unfinished.** A `knowledge` label says where the answer should come from, not that the note
  exists; authoring the notes is M4.
- **Single turn.** `clarify` means vague as a standalone message; M4 may resolve some with context.
- **Cloud latency and availability** for Model-2 depend on the network and a signed-in Ollama account.
- **One prompt.** Both models use the same request; a prompt tuned for one of them would invalidate the
  comparison.

## 7. Reproduction

```bash
ollama pull clef:cloud      # host, once; requires an Ollama account
make router-spike           # builds the spike server, pulls tev1, runs both arms
```

The run writes `results/<run-id>.json` and `.md`: every choice, timing, model digest, prompt version, sample
hash, and the cloud-egress note. Unit tests cover the sample, the prompt loader, the arm plumbing and the
precision/recall arithmetic; they do not call a model.
