# AI usage report — Hermes Football

Course criterion 2. What was delegated to AI agents, what a human reviewed, what was rejected, and what proves the
result holds. Entries are added in the same commit as the work they describe.

This project is built mostly by agents. The report is how a reviewer sees the difference between work that was
checked and work that merely looked right.

## How to add an entry

- **Delegated** — what the agent was asked to produce, and which agent produced it.
- **Reviewed** — what a human read line by line, and what changed as a result.
- **Rejected or revised** — what an agent proposed and a human threw out or corrected, and why. An empty column is a
  smell, not a compliment.
- **Evidence** — the test, scan, lint run, commit or document that shows the result holds. For documentation work
  that is cross-document consistency and review; automated tests begin with M1 and take over from there.

## Sessions recorded in detail

### S1 — Align the M1 wording between the two spec documents (commit `6b00f41`, 2026-10-10)

- **Delegated:** read `AGENTS.md` and `_docs/`, summarise the documented milestones, then reconcile M1 between
  `_docs/scoping.md` and `_docs/product-spec.md` and commit. Agent: DeepSeek Harness coding agent.
- **Reviewed:** the human set the rule for the tie (the most recent statement wins) and approved the resulting
  wording before the push.
- **Rejected or revised:** the agent had first reported the two documents as merely worded differently. On inspection
  the spec listed the API contract as an M1 deliverable although M0 already delivered it and `AGENTS.md` recorded the
  contract as reviewed. The commit body records the corrected reasoning rather than the original claim.
- **Evidence:** commit `6b00f41`; both documents now state the same M1, and `AGENTS.md` next step 1 says the same thing.

### S2 — Scope the notes corpus, the embedding model and the router (commit `ec73139`, 2026-10-10)

- **Delegated:** answer three open scoping questions — is there a compiled list of the notes, how does the agent
  choose between SQL and retrieval, and which embedding model is the default — and write the answers into the
  doc-base as decision records.
- **Reviewed:** the human answered five follow-up questions before anything was written. Two of those answers changed
  the outcome: the corpus was fixed as English-only, and the embedding target was corrected (below).
- **Rejected or revised (two, both worth reading):**
  1. **The agent was wrong about a model.** It reported that `embeddinggemma-2:270m` was not a valid Ollama tag and
     recommended the older `embeddinggemma:300m` instead. The human supplied the library URL; the agent verified it,
     found the tag real (378 MB, 768-dimensional output) and corrected the record before it was committed. Cause: it
     had read only the sibling `embeddinggemma` tag list, not the `embeddinggemma-2` page. The facts table in
     `_docs/decisions/0002` now cites its source and the date it was checked.
  2. **A recommendation was overruled by method.** The agent proposed adopting deterministic-first routing by
     default. The human required an experiment instead: both routing designs must be sampled and scored by an
     LLM-as-judge against hand-checked expectations before either is adopted. That became M3b and
     `_docs/decisions/0003`, which is deliberately still *Proposed*.
- **Evidence:** `_docs/decisions/0001`–`0003`; the product spec gains R-F6.5 and R-F6.6 with acceptance criteria; the
  model facts were verified against the vendor pages on 2026-10-10 (the agent had no other source, and said so).

### S3 — M6 scope and the MCP transport (2026-10-10, the commit that adds this report)

- **Delegated:** choose the M6 wording that better matches the 14 course criteria, align the MCP transport across the
  documents, and start this report.
- **Decision rule given by the human:** the better-aligned wording wins. The agent picked the product spec's
  `CI/CD, observability, security, AI-usage report` over scoping's `Automation, monitoring, security`, because every
  noun in it names a row of the criteria map (§7): CI/CD is criterion 11, observability and security are criterion 13,
  the AI-usage report is criterion 2 — while "automation" and "monitoring" named criterion 13 twice and left
  criterion 2 unclaimed.
- **Reviewed:** the human confirmed the HTTP transport decision and the report's creation.
- **Rejected or revised:** the agent had left the MCP `stdio`/`HTTP` contradiction in place for two turns, reporting
  it rather than resolving it. The human chose HTTP, matching `_docs/product-spec.md` §4, which explains that a stdio
  server would have to live inside the Hermes image.
- **Evidence:** `_docs/scoping.md` §8 and `AGENTS.md` now name the same four M6 artifacts, and outside this report the
  only remaining mention of stdio is the product spec's rationale for avoiding it.

## Sessions that predate this log (backfill needed)

These commits were made before this report existed. What is recorded here is only what the commit messages state;
the humans involved should add the delegation, review and rejection detail, or mark the row as closed.

| Commit | Date | Work | Missing from the record |
| --- | --- | --- | --- |
| `2dde99e` | 2026-10-09 | Initial commit: scope, product spec, API contract and dev tooling | Who drafted the contract, what was reviewed line by line, what was thrown away |
| `9a740ba` | 2026-10-10 | Verify free-tier API capabilities and align the contract with the probe | Which calls were probed by hand, what the first contract draft got wrong |
| `6c40961` | 2026-10-10 | Remove host-install guide: Hermes runs in Docker in this project | Which agent proposed the host install and why it was rejected |
| `7d922e5` | 2026-10-10 | Add the Compose project section to the product spec | The container-versus-terminal-backend reasoning, if any of it was contested |
| `ac56e5c` | 2026-10-10 | Rewrite the scoping doc in plain language, add the SQL-vs-RAG worked examples | What the first plain-language draft got wrong |
| `1174605` | 2026-10-10 | Give the knowledge notes an owner in the plan | The gap that prompted it (a plan that promised rules answers with no milestone owning the notes) is in the commit body; the review detail is not |

## Where the prompts live

`prompts/` is the versioned prompt bank (see its README). It is empty today: no prompt has yet shaped product
behaviour, because no application code exists. The first entry will be the router spike's LLM-as-judge prompt, which
`_docs/decisions/0003` requires to be versioned before its numbers are reported.
