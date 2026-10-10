# prompts/ — the versioned prompt bank

Course criterion 2: every prompt that shapes product behaviour lives here as a file, reviewed in the same commit as
the change it makes, so a prompt can be diffed and blamed like code.

## Conventions

- One file per prompt: `NNNN-<slug>.md` (for example `0001-router-spike-judge.md`).
- Each file opens with a header block: `version`, `used by`, `model`, `date`, `owner`, `status`.
- A change is a new version in the same file plus a line in `_docs/ai-usage-report.md`. Never a silent edit: a prompt
  that changes what the product says is a behaviour change, and `_docs/product-spec.md` changes with it.
- The eval harness stores the prompt version alongside each run, so scores stay comparable across versions
  (`_docs/product-spec.md` R-F9.3).
- Secrets never appear in a prompt (`AGENTS.md` hard rule 6). User messages are never copied here; if a real
  conversation informs a prompt, it is paraphrased and the chat ID is dropped.

## Planned first entry

`0001-router-spike-judge.md` — the LLM-as-judge prompt for the M3b routing spike, required by
`_docs/decisions/0003` before that spike's numbers may be reported.
