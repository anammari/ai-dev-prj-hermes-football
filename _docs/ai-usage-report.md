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
     `_docs/decisions/0002` now cites its source and the date it was checked. The sequel is S4: the tag was real and
     still unusable here, so the recommendation the agent was overruled on is the one now shipped, for a different
     reason.
  2. **A recommendation was overruled by method.** The agent proposed adopting deterministic-first routing by
     default. The human required an experiment instead: both routing designs must be sampled and scored by an
     LLM-as-judge against hand-checked expectations before either is adopted. That became M3b and
     `_docs/decisions/0003`, which is deliberately still *Proposed*.
- **Evidence:** `_docs/decisions/0001`–`0003`; the product spec gains R-F6.5 and R-F6.6 with acceptance criteria; the
  model facts were verified against the vendor pages on 2026-10-10 (the agent had no other source, and said so).

### S3 — M6 scope and the MCP transport (commit `eed27f9`, 2026-10-10)

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

### S4 — M1: the schema, the notes corpus and the embedding provider (commit that lands M1, 2026-10-10)

- **Delegated:** build and test M1 as `_docs/product-spec.md` §4 and §8 define it — the Alembic migration matching
  `openapi.yaml`, the notes corpus with its manifest, the local embedding provider in Compose, one note indexed end to
  end — and report what the tests found.
- **Reviewed:** the human reviewed the plan and this outcome; the one judgement it asked for (which model to pin) was
  already answered in S2, and M1 followed it until the container disagreed.
- **Rejected or revised (four, all caught by running the thing rather than reading it):**
  1. **The pinned embedding model cannot run in the stack.** `embeddinggemma-2:270m`, chosen in S2 and pinned in
     `_docs/decisions/0002`, is published in Ollama's MLX/Safetensors packaging (`application/vnd.ollama.image.tensor`
     layers only). Pulling it inside the `ollama` Compose container fails with *"this model requires MLX support, but
     the MLX runtime is not available"*. MLX is Apple-only; the deployment is a Linux container. `embeddinggemma:300m`
     pulls and probes to the same 768 dimensions in that container, so nothing in the schema changed. Recorded as
     `_docs/decisions/0004`, which supersedes `0002` rather than editing it. **The agent had read the library page,
     not the container** — the same class of mistake as S2, caught this time by an integration test instead of a human.
  2. **The read-only role test was passing for the wrong reason.** The first version granted the statements via
     `SET ROLE` and rolled back between them; `SET ROLE` is undone by a rollback, so the second statement onwards ran
     with the owner's rights. The test now logs in *as* the agent role and opens a connection per statement. Verified
     by hand in `psql` before rewriting it.
  3. **A too-long identifier only breaks on Postgres.** The naming convention generated a 67-byte unique-constraint
     name for `standings`; the migration failed half way on Postgres after passing every SQLite test. The constraint is
     now named explicitly, and a unit test asserts every identifier fits in 63 bytes.
  4. **The test image did not contain `openapi.yaml`.** The contract-coverage test read the contract off the host path
     and passed locally, then failed in the container the tests actually run in.
- **Evidence, all reproducible with `make up && make models && make test && make itest`:**
  - 35 unit tests and 7 integration tests pass; `ruff check` is clean.
  - Integration: `select version()` is PostgreSQL 16 with pgvector 0.8.7, `knowledge_chunks.embedding` is
    `vector(768)`, the HNSW index uses `vector_cosine_ops`, the provider returns 768 floats, the agent role can read
    and cannot insert, update, delete, create, alter or drop.
  - End to end: `python -m ingest.knowledge index` writes 5 chunks for the seed note and writes 0 on the second run;
    `search "how old is the data and is it live"` returns the note's passages, best score 0.402.
  - `tests/contract_map.py` plus `tests/test_contract_coverage.py` fail in both directions when the schema and
    `openapi.yaml` drift apart. They currently flag one real gap: `agent_turns.route`/`route_source`/
    `route_confidence` are required by `AGENTS.md` rule 10 but absent from contract v0.1.0. M3 owns the fix; it is
    written down in `_docs/data-model.md` rather than silently allowed.

### S5 — M2 ingestion pipeline and its review fixes (verified live)

- **Delegated:** the M2 build and the fixes in `_docs/handoff-m2-fixes.md` were done in coding sessions; a task agent
  was used only for a shell chore.
- **Reviewed:** human review found that live acceptance had never run. Running it exposed three defects that every
  stubbed test missed: (1) a 404 on EC standings/scorers aborted every run, (2) upstream rejects `/matches` ranges
  over 10 days with HTTP 400, so 90-day windows loaded no fixtures, (3) upcoming knockout fixtures with undecided
  teams crashed normalization. All three are fixed with regression tests (the stub client now enforces the 10-day
  cap). 50 unit and 9 integration tests pass, ruff is clean, and `make itest-isolated` provides a throwaway DB.
- **Rejected or revised:** no hardcoded competition list; a failing optional resource now yields `partial`, not
  `failed`; bronze is pruned after 30 days; "one working copy, no worktrees" was added to `AGENTS.md` after two
  worktrees on one Compose volume broke `make up`.
- **Evidence:** a live run on the retained volume loaded 13 competitions and 9,895 matches (162 calls, ~19 minutes,
  `partial` because EC has no standings). The measured score delay is about 1.5-3 minutes (match 555033), recorded in
  `_docs/scoping.md` §3 and the delay policy note — but that figure was read by hand out of the stored poll payloads,
  because `make score-delay` itself ended `failed`: it waited for a finished match with no score, a state the provider
  never produces. The tool is repaired in S6. Lesson: stubbed providers cannot find provider rules; only a real run
  did.

### S6 — M2 close-out: the review, the README index, the score-delay tool and the Ollama image

- **Delegated:** none. A human asked an agent to review the M2 fixes, sync the README with the course criteria, delete
  the completed handoff and repair `make score-delay`; the agent made those edits under review, and the container work
  was done directly.
- **Reviewed:** every claim on the branch was checked against the live database and the stored payloads rather than
  against the docs. Two did not survive: `make score-delay` could only ever exit non-zero, and its documented figure
  had been read by hand out of the poll payloads. Both are now fixed and disclosed in S5 above. The review also
  confirmed what was sound — 9,895 matches loaded live, EC's 404 isolating to `partial`, and the branch a clean
  fast-forward on `main` with no secrets in its diff.
- **Rejected or revised:** the score-delay command's premise was rejected outright — the provider publishes the score
  while the match is `IN_PLAY`, so there is no scoreless-finished window to wait for; it now measures the provider
  `lastUpdated` to fetch gap. A first attempt at its default match selector was itself wrong, picking a fixture
  scheduled for 2027, and a human caught it in a live run, so it is now bounded to matches that have kicked off. On
  the container side, a thin `RUN rm -rf` over the Ollama image was rejected because it reclaims nothing; the image is
  flattened instead. Keeping the duplicate `ollama/ollama:latest` tag was also rejected, being a floating tag that
  would silently pull a second 7 GB image later.
- **Evidence:** 54 unit and 9 integration tests pass, ruff is clean. A bounded live run against match 555032, still in
  play, gave `statuses_seen: {"IN_PLAY": 10}`, `score_published_before_full_time: true` and a median observation lag
  of **104 seconds** over ten polls — the 1.5-3 minute claim re-derived from a live match rather than by hand — and the
  ledger's first `succeeded` score-delay run. The Ollama image went from 7.05 GB to 637 MB with the model server
  verified by the two integration tests named in [decision 0005](decisions/0005-ollama-image.md); Docker's disk image
  went from 13 GB to 6.9 GB.

### S7 — The Copilot pull-request review of M2: sixteen findings, fourteen applied (commit that lands this entry, 2026-10-13)

- **Delegated:** a second opinion on the M2 branch, asked of Copilot's pull-request review on PR #1 after the human
  review in S6. It raised sixteen findings. Each was reproduced against the retained volume, or against a scratch
  database, before any code was touched — the point of a second reviewer is to disagree usefully, not to be obeyed.
- **Reviewed and applied, with the reproduction that justified each one:**
  - *Preserve omitted team metadata during summary upserts* (High). Real, and the damage was already in the data:
    `/matches` and `/standings` embed only `id, name, tla, crest`, so writing the absent keys as `None` had blanked
    `area` on **all 360** teams. Only the fields a payload actually carries are written now.
  - *A malformed provider row aborts the whole day.* Reproduced with a standings row missing its points total: the
    `ValueError` reached the outer handler, failed the run and skipped every remaining competition and match window.
    `ValueError` and `UpstreamError` are caught at the two boundaries; a database fault still aborts the run.
  - *Retention never runs when collection fails.* The prune sat inside the main `try`, so a run of failed days would
    let bronze outlive its window.
  - *Coverage flags keep their default on a withheld table.* `coverage_standings` defaults to true, so EC's 403 was
    logged but the flag still claimed the table was served.
  - *A stale `is_current` season flag is never retired.* Latent rather than visible today — no competition has rolled
    over yet — but the first rollover would leave two seasons marked current and every such query returning both.
  - *`make ingest` exits 0 on a failed run*, which tells CI the day landed when it did not.
  - *Bronze written by score-delay measurements is never pruned*, because nothing else prunes those rows.
  - *The `0002` downgrade cannot run once a new enum value is stored.* Reproduced on a scratch database, not the
    retained one: it failed with a `CheckViolation` on `ck_competitions_type_valid`, and passes now.
  - *The README promises a working stack in three commands* from a clean checkout, while `.env.example` ships a
    placeholder token that both the scheduler and the CLI reject, and a fresh `ollama` volume holds no embedding
    model. The prerequisite is stated, and `make up` now pulls the model when the volume is empty.
  - Three stale `AGENTS.md` lines: the score-delay description, the unit-test count, and a next step naming a
    provider state that cannot occur.
- **Rejected, and why:**
  - *Serialize ingestion and coordinate shared rate limits across all clients* (High). Real only in the narrow sense
    that two clients hold separate token buckets — but those buckets are the safety net, not the mechanism. The
    primary pacing reads `x-requests-available-minute`, which is account-wide, so a second process does not get a
    second quota; the exposure is a one- or two-request transient that the client already answers with a paced
    retry. A shared limiter or a cross-process lock is an architectural change that does not belong in this pull
    request, and declining it keeps the PR reviewable.
  - *Add a restart policy to the ingest scheduler.* Fair about an out-of-memory kill, but `make up` proves the
    scheduler is alive five seconds after start-up precisely so that an invalid token fails loudly. An automatic
    restart makes that probe sample a sometimes-up, sometimes-down container. The two changes have to land together,
    so this is left as its own task rather than applied here.
- **Evidence:** 64 unit and 9 integration tests pass, ruff is clean. Ten tests were added; reverting only the source
  files and re-running them shows **seven failing against the pre-fix code**, which is what makes them regression
  tests rather than decoration. The migration was exercised in both directions on throwaway databases.

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
