# prompts/ — the versioned prompt bank

Course criterion 2: every prompt that shapes product behaviour lives here as a file, reviewed in the same commit as
the change it makes, so a prompt can be diffed and blamed like code.

## Conventions

- One file per prompt: `NNNN-<slug>.md`, numbered in the order the prompts were written.
- Each file opens with a header block: `version`, `used by`, `model`, `date`, `owner`, `status`.
- A change is a new version in the same file plus a line in `_docs/ai-usage-report.md`. Never a silent edit: a prompt
  that changes what the product says is a behaviour change, and `_docs/product-spec.md` changes with it.
- The eval harness stores the prompt version alongside each run, so scores stay comparable across versions
  (`_docs/product-spec.md` R-F9.3).
- Secrets never appear in a prompt (`AGENTS.md` hard rule 6). User messages are never copied here; if a real
  conversation informs a prompt, it is paraphrased and the chat ID is dropped.

## Entries

| File | Prompt | Status |
| --- | --- | --- |
| [`0001-m3-backend-api.md`](0001-m3-backend-api.md) | Build the M3 API against `openapi.yaml` | Reviewed, shipped |
| [`0002-router-model-comparison.md`](0002-router-model-comparison.md) | The one routing request both models receive in the M3b routing comparison, so the model is the only variable | Used by both arms; comparison recorded in `_docs/scoping.md` §8 |
| [`0003-agent-router.md`](0003-agent-router.md) | The M4 production routing request: surface, tool, a binding safety question and a simple/complex label in one pass | Reviewed; used by `agent/router.py` and the M4 holdout run |
| [`0004-complex-planner.md`](0004-complex-planner.md) | Plan up to four allowlisted tools for a complex database question | Reviewed; used by `agent/gateway/planner.py` |
| [`0005-complex-composer.md`](0005-complex-composer.md) | Compose a cited answer from the collected results with `beam:cloud` | Reviewed; used by `agent/gateway/answer_composer.py` |
| [`0006-complex-verifier.md`](0006-complex-verifier.md) | Check a complex draft's factual claims against the results | Reviewed; used by `agent/gateway/answer_verifier.py` |
