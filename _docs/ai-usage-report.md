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

- **Delegated:** choose the M6 wording that better matches the course criteria, align the MCP transport across the
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

### S8 — M3: the backend API against `openapi.yaml` (branch `anammari-m3-backend-api`, 2026-10-13)

- **Delegated:** the whole of M3 to the DeepSeek Harness coding agent, in the root checkout on a branch off `main`,
  after a plan was approved: read `AGENTS.md`, `_docs/scoping.md` §7–8, `_docs/product-spec.md` §F3, `openapi.yaml`,
  `_docs/data-model.md` and the model layer; then build `backend/` (FastAPI) against the contract, with unit tests,
  one integration test and the Compose wiring. The plan named the files, the error semantics and the acceptance
  criteria before any code was written, and the prompt is versioned in
  [`prompts/0001-m3-backend-api.md`](../prompts/0001-m3-backend-api.md).
- **Decided by the human, and binding on the agent:**
  - **Admin scope: read-only.** All `GET` operations are implemented; the two write operations answer a declared
    404 naming M5. No write path and no write credential exist in the API, which keeps `AGENTS.md` rule 4 true by
    construction rather than by discipline.
  - **Leave the router alone.** The plan had a routing stub; `_docs/decisions/0003` needs the M3b spike's numbers first,
    so the turn log *records* `route`/`route_source`/`route_confidence` (rule 10) but nothing chooses them yet.
  - **The contract changes with the behaviour that needs it, in the same commit** — which is how `AgentTurn` gained
    the three route fields in v0.2.0, and how the corrections below landed rather than being filed as issues.
  - **Criterion 5 and 6 are worth points and are graded on evidence**, so the drift test is a deliverable, not a
    by-product: it reads `openapi.yaml`, and the validator it uses is itself tested to fail on a renamed field.
- **Rejected or revised during the build, and what made each one visible:**
  - *A generated OpenAPI document served at `/openapi.yaml`,* and separately *comparing routes via FastAPI's internals*
    (`app.routes` holds `_IncludedRouter` objects in 0.143, with no `.path`). Rejected: the contract file is served
    verbatim, and the comparison uses the public `app.openapi()`. Serving a generated document would have made the
    drift test self-confirming: the API would have agreed with itself.
  - *The agent's first freshness rule treated any `succeeded` run as a refresh.* The retained ledger contains nine runs
    with a `NULL` competition scope (the score-delay polls), so that rule would have reported every competition fresh
    after a single match poll. A test built on the real ledger shape now pins "a run with no scope refreshes nothing".
  - *`TeamForm.matches[].score` was duplicated verbatim from `ScoreLine`* instead of referenced; the human's review of
    the diff turned it into `allOf: [$ref ScoreLine]`, with a description that the scoreline is as published and not
    rotated by `home` — the mistake a model would have made when reading it.
  - *`KnowledgeHit.source_file` and `Match.last_updated` were both described in a way the data contradicts* (repo-relative
    example, and "our ingestion write time" for the provider's own stamp). Corrected in the contract, because both
    would have made an agent mis-cite a source or overstate an age.
  - *A `minScore=0` search returned nothing.* Cosine can be negative on the SQLite path and the score was clamped after
    the threshold instead of before, so the one value that means "keep everything" dropped everything. Found by a test,
    not by reading.
  - *The API's first response shape for a competition with no table was 404.* The contract's own words distinguish
    "not in the database **yet**" (503, "no data") from "no such resource" (404), and the code now implements that
    distinction literally, including the contract's example sentence.
  - *The agent's first test seed failed on `FOREIGN KEY constraint failed` and, after that, on insertion order.* Two
    real causes: `Standing.id` is an autoincrement integer and was being given a UUID, and SQLAlchemy does not order
    inserts across mappers by a plain `ForeignKey` — the fixture now flushes per dependency group, with the reason in
    a comment. The ingestion pipeline never hit the second one because it opens a session per row.
  - *The routers were written with `Depends()` in argument defaults,* which ruff rejects 28 times (`B008`). Rewritten
    as `Annotated[...]`, which is FastAPI's own recommendation and keeps the lint rule meaningful instead of muted.
  - *`.env` needed a new required setting* (`API_AGENT_TOKEN`). It fails closed rather than open: with no token, every
    agent-facing request is 401 and the startup log says why, so a forgotten token is a closed door.
- **Sent to an adversarial reviewer before the branch was offered for merge** (a second agent, told to falsify the
  suite's claims rather than read it sympathetically, with the milestone frozen and every probe reverted afterwards).
  Eight findings came back, four of them merge-blocking; all eight are now either fixed with a regression test or
  written down. What the reviewer found is the part of this milestone the author's own tests could not find:
  - *The drift test could not see a route hidden from the generated document.* It built "what the app serves" from
    `app.openapi()`, and FastAPI leaves `include_in_schema=False` routes out of that document, so the reviewer added an
    **unauthenticated** route and the whole suite passed. Routes are now read from the router tree, which also catches a
    second route reusing a documented `operationId` (the reviewer's second probe: it shadowed `/competitions` and
    answered without a token).
  - *Parameter schemas were compared by name and requiredness only.* `limit: Query(ge=1, le=100) = 20` against a
    contract saying `maximum: 200, default: 50` passed while rejecting a documented-legal request. Bounds, format,
    pattern and default are compared now, with two narrow exemptions documented in the test.
  - *The validator dropped `minItems`/`maxItems`,* so the contract's "exactly two teams" was unenforced; a meta-test now
    walks the file and fails on any constraint keyword the translator would silently ignore.
  - *The rule 3 and rule 4 scans were blacklists an AST can walk around* (`from ingest import client`,
    `session.execute(text("DELETE FROM matches"))`, a second engine from owner credentials). They are now a whitelist of
    what `backend/` may borrow from `ingest`, a transitive walk proving those modules never import the upstream client,
    a check that every hand-written statement starts with `SELECT`, and one engine-building module in the package.
    Compose is asserted too: no provider key on the `backend` service, no Docker socket, read-only mounts, one port.
  - *A client could reach a 500* by sending an id or an `offset` past 64 bits (`OverflowError` in the driver). The
    contract now declares `format: int64` where the columns and driver binds impose it, the routers enforce that range,
    and the request answers `400 invalid_parameter`. The contract changed in this commit because the behaviour did.
  - *Freshness said `fresh` for a competition the ledger only listed.* `ingest_runs.competitions` is the plan the run was
    *given*, so a run that collected nothing still refreshed its codes — while `/competitions/{code}/matches` answered
    `data_not_available` for the same code. A competition with no stored rows is now `unknown`, never `fresh`, and a run
    stamped in the future (container clock skew) is ignored instead of printing a negative age.
  - Two further findings were **dismissed with reasons** rather than fixed: an out-of-enum `last_status: "running"` and a
    `succeeded` run with a `NULL` `finished_at` are both unreachable from the shipped ingestion (the writers set scope,
    status and `finished_at` together at finalization). The first is nonetheless now impossible by construction — only
    finished runs are read — and the second has a test. Query-boolean leniency (`?grounded=yes`) is left as FastAPI's
    standard parsing, with a comment saying so.
- **Three more findings came from running the suite where the reviewer could not: against the retained volume.** The
  integration run is what caught them, and two are the kind of thing a review of the source cannot see:
  - *An injected embedder was closed by the app on shutdown.* The stack suite shares one module-scoped `OllamaEmbedder`
    across several apps; the first app to stop closed the HTTP client, and every later embedding call raised "Cannot
    send a request, as the client has been closed" - which surfaced as one 500 in the middle of the contract sweep. The
    app now closes only what it built (the engine guard already did), and a unit test holds both halves of that rule.
    The unit suite had missed it because the deterministic embedder has no `close` to call.
  - *The sweep sent the contract's example match id (`/matches/419823`) to a volume whose ids start at 560912,* because
    ids were patched into the finished URL. `matchId` and `code` are path parameters and the helper had already
    substituted the examples, so the fix was to pass real ids as overrides. A test that only ever runs against fixtures
    cannot notice this.
  - *The ledger column is `json`, not `jsonb`,* and unscoped runs are stored as SQL NULL rather than an empty array. The
    API serves both as `[]`; the test now asserts that property instead of one spelling of the type.
- **Evidence:** `make test` is 231 unit tests green (64 before M3, 199 when the review started) and `make lint` is clean;
  13 integration tests were added for this milestone (22 collected in total). `tests/test_api_contract.py` covers route
  and operation coverage in both directions — read from the router tree — parameter name, requiredness, bounds, format
  and default, the `operationId` uniqueness of the app as well as the contract, a behavioural check that every enum
  parameter rejects an unlisted value, every implemented `GET` response against its schema, the error envelope, the
  unimplemented-operation list, version equality and the verbatim contract file — plus
  `test_the_validator_fails_on_a_drifted_response`, which proves the check can go red. The stack suite repeats the sweep
  on Postgres and asserts that the engine the request path holds is `agent_readonly` and cannot write.
- **Still open, and written down rather than papered over:** the two admin writes need a claimable queue before they
  can be real (M5), `standings.group_label` and `standings.matchday` are contract fields the live data never fills,
  and the drift test's Postgres half is skipped on a throwaway volume that has no ingested rows
  ([`_docs/data-model.md`](data-model.md) open items).

### S9 — M3b: comparing two model-first routers (branch `anammari-m3b-router-spike`, 2026-10-19)

- **Delegated:** the routing comparison to the DeepSeek Harness coding agent, in the root checkout on the existing
  branch. The task: remove the regex router entirely, compare two decision models on the same 85-question sample and
  the same request, report precision and recall, delete the previous routing artifacts, and record the result.
- **Decided by the human, and binding on the agent:**
  - **No deterministic pre-router and no regex.** The owner removed the approach outright; routing is model-first.
    The measured problem with the old rules was precision (87% overall, 75% on holdout), not speed — regex runs in
    microseconds — but the direction is removed on the owner's call and the docs say so.
  - **Model-1 `tev1:0.8b` (local) versus Model-2 `clef:cloud` (cloud)**, same dataset, same distributions,
    precision/recall as the report.
  - **The previous routing model and its artifacts were removed** from Docker and from the docs, and the old results deleted.
- **Rejected or revised, and what made each visible:**
  - *Deterministic routing* — removed with its code and tests; no fallback, no threshold, no tie-break.
  - *The previous judge and its prompt* — removed with the previous artifacts; this spike scores against hand labels
    only. `R-F9.2` applies again only if a judge is introduced.
  - *A cloud model as a drop-in winner* — `clef:cloud` won on quality but sends every message to Ollama's cloud. The
    spike recorded that as a blocker; the owner then **signed the egress off on 2026-10-20** after seeing the
    numbers, and the product spec was changed to say which data leaves the machine. The 85 messages were synthetic
    eval text; production messages will not be.
  - *`tev1:0.8b` as the local answer* — it failed safety: 2/5 adversarial refusals, 1/5 refusal-class, knowledge
    recall 0.29. The local model is not viable yet, and the record says so.
  - *`clef:cloud` refusal* — 5/5 adversarial but only 3/5 refusal-class, and `clarify` precision 0.18; it asks back
    too often. The model was signed off anyway; the refusal gap is an explicit M4 gate, not something the sign-off
    pretends is solved.
- **Evidence:**
  - `make lint` clean; `make test` **256 unit tests** pass, including the sample, prompt loader, arm plumbing and
    precision/recall arithmetic.
  - The harness ran both models on 2026-10-19 (`2026-10-19T12-40-46Z`): tev1 holdout 53% accuracy, macro
    P/R/F1 0.59/0.45/0.43; clef 71%, 0.78/0.79/0.70. Neither passed the safety gates. Results, per-route
    precision/recall and every choice are in `evals/routing/results/`.
  - Decision 0003 is Accepted: `clef:cloud` is selected, with the cloud egress signed off; production wiring waits
    for the M4 safety gate. `_docs/scoping.md`
    §8 carries the table; `AGENTS.md` and `README.md` no longer claim a deterministic router.

### S10 — M4 sources: the URL table behind the notes (branch `anammari-m4-agent`, 2026-10-21)

- **Delegated:** compile the official source URLs for the notes planned in decision 0001, put them in a separate
  `_docs/notes-sources.md` table, and make sourcing an explicit M4 task. Documentation only; no code was touched.
- **Decided by the human, and binding on the agent:** URLs live in a separate table, not in
  `hermes/agent-knowledge/manifest.yaml`. The manifest keeps the short citation; the table holds the checkable link,
  publisher, season and date.
- **Rejected or revised, and what made each visible:**
  - *Search API unavailable.* Used DuckDuckGo's HTML page and direct fetches instead. Search results from Wikipedia,
    Sky Sports and stats aggregators were rejected as sources; they were used only to find the official page.
  - *The provider contradicts itself.* The pricing and coverage pages say 12 free competitions and list squads and
    goal scorers as paid; the live probe on 2026-10-10 found **13** competitions and returned squads and top scorers
    on the free key. The table records both, and the notes must follow the probe (`_docs/scoping.md` §3).
  - *Clean sheet has no official definition.* No law or competition regulation defines it. Recorded as an owner
    decision with a recommendation, rather than inventing a regulatory citation.
  - *The EFL statement and the UEFA document pages render with JavaScript.* The EFL regulation PDF is the authority;
    the statement is only the dated announcement of the move from four to six clubs.
  - *A first assumption about Serie A was wrong.* The 2026/27 FIGC communiqué (244/A, 27 May 2026) does not simply
    rank on head-to-head: it defines a single play-off for 1st, a two-legged 17th-v-18th play-off, the *classifica
    avulsa* for more than two clubs, and no play-off when a club is in a UEFA final. The table now cites the
    communiqué and the note must follow it, not the older summary.
- **Evidence:** every URL in `_docs/notes-sources.md` was opened on 2026-10-21 (HTTP 200 for pages, 206 for ranged
  PDF requests). The table is linked from `_docs/scoping.md` §8 (M4 "done when"), `_docs/product-spec.md` R-F6.1a,
  `AGENTS.md` next step 4 and the README. No test is claimed for a document; the check is a reviewer opening the
  links.

### S11 — M4: the routing gate, the MCP tools, the Telegram gateway and the notes (branch `anammari-m4-agent`, 2026-10-22)

- **Delegated:** the M4 build to the DeepSeek Harness coding agent, in the root checkout on the milestone branch,
  after the owner signed off the plan. Two independent subagents did the holdout: one wrote 60 questions from the
  class definitions, the other audited every label. Neither read the router request, `agent/` or the archived
  sample. The AI-usage report, the decision records and the guide were written by the coding agent and reviewed.
- **Decided by the human, and binding on the agent:**
  - One small routing slice first, then the tool surface, the Telegram interface and the notes; split if too large.
  - The gate must be model-first: no regex and no deterministic pre-router. The same-pass safety question with a
    hard veto was approved on that basis.
  - Translation of the Italian and Spanish sources happens at authoring time, in the note, with no translation API
    and no runtime service.
  - The scorer gap is explicitly refused rather than answered from the wrong table.
  - Telegram is the M4 interface; a web-chat substitute was not needed.
- **Rejected or revised, and what made each visible:**
  - *Running the Nous Hermes Agent image as the gateway.* Rejected for M4: it owns its tool loop, so the gate
    could not be guaranteed before every tool call, and its model provider would need a second egress decision for
    tool output and notes. Recorded in decision 0007; the MCP surface remains the contract and the optional
    deployment template is in `hermes/config.yaml`.
  - *A second model to make answers conversational.* Rejected: tool output and note text would leave the machine.
    The composer restates the payload; the cost is that answers are not chatty.
  - *A deterministic deny-list for injections.* Rejected before code, per rule 10 and decision 0006.
  - *A threshold on the model's probabilities to "fix" the clarify over-prediction.* Rejected as a deterministic
    post-router; the preference instruction fixed most of it model-first, and the holdout measured the rest.
  - *The archived 85-question sample as the M4 holdout.* Rejected: the request changed, so reusing it would have
    measured the old prompt against new behaviour. A new independent 60-question holdout was written and frozen.
  - *A first draft of the notes that cited LaLiga's general regulation for the tiebreak.* Corrected: that document
    only sets the points; the criteria are in RFEF Circular 84, Article 10.
- **Evidence:**
  - Routing: `make test` has 323 unit tests, all passing; `make lint` clean. The holdout ran once:
    gated macro-F1 0.979, raw 0.906, 8/8 adversarial, 4/4 fabricated, 3/3 refusal, 4/4 unsupported, zero false
    refusals, zero database→notes. One miss (`results-h3`).
  - Tools: `tests/test_mcp_server.py` covers every tool against a fake backend and the JSON-RPC surface;
    `tests/integration/test_mcp_stack.py` runs six tests against the real API and the running container.
  - Gateway: `tests/test_gateway.py` covers composition, the one-tool pipeline, the allowlist and commands;
    `tests/integration/test_gateway_stack.py` runs five end-to-end turns against the real router, MCP server,
    writer role and corpus (database question, notes question, override, scorer refusal, clarify).
  - Notes: `make check-notes` passes for 13 reviewed notes; `make index-notes` wrote 41 chunks and removed the five
    chunks of the old draft. Retrieval was checked by hand for all five rule notes before the gateway test.
  - Manual: `make ask Q="where are Arsenal in the table?"` answered with the data timestamp and `route: tool`;
    `make ask Q="how does the championship playoff work?"` answered with the note passage and its citation.
  - Not yet run: the live Telegram smoke test. No bot token exists in the repository or the retained `.env`; the
    owner's step and the exact commands are in `_docs/m4-guide.md`.

### S12 — M4 answer layer: complexity split and Beam (2026-10-22, branch `anammari-m4-agent`)

- **Delegated:** extend the M4 gateway so `clef:cloud` labels a message `simple` or `complex`; keep the one-tool,
  deterministic path for simple questions; add a planner, several tools or notes, and a `beam:cloud` composer for
  complex ones; verify citations and fall back deterministically. Keep all of it in M4, not a sub-milestone.
- **Decided by the human, and binding on the agent:**
  - Complexity is a fourth label in the same `clef:cloud` request, not a second router or a regex.
  - `beam:cloud` is the response generator for complex queries; the owner accepted its cloud egress for that path.
  - Operational work stays in M4; sub-milestones are for spikes only.
  - The final Mermaid pipeline diagram is a later task, after all milestones, in `README.md`.
- **Rejected or revised, and what made each visible:**
  - *The deterministic-only answer layer* — rejected by the owner: it cannot combine standings with form, or
    synthesise across notes. The simple path kept it; the complex path replaced the single-tool assumption.
  - *A local chat model for the composer* — not chosen; `beam:cloud` was selected for speed and cost. This is a new
    signed-off egress for complex questions, recorded in decision 0007 and the product spec §4.
  - *Sending simple answers to Beam too* — rejected: the simple path stays local and cheaper.
  - *A full claim-by-claim verifier* — not built in this slice; the verifier checks the required timestamp/source and
    the note file, with the deterministic composer as fallback. A fuller answer-verifier remains a follow-up.
  - *Closing the scorer gap in this slice* — still open: the planner can only choose exposed tools, so a scorer
    question is refused rather than answered from the wrong table.
- **Evidence:**
  - `clef:cloud` prompt v2 classified the probe set correctly: simple table lookup, simple one-note rule, complex
    standings+form comparison, complex two-note comparison. The same frozen holdout re-run scored gated macro-F1
    0.960 with all safety gates still passed (`2026-10-22T12-19-58Z`).
  - `make ask Q="Compare Arsenal's league position with their recent form and say whether they are in the title
    race."` produced `complexity: complex`, two tool calls, a Beam answer with the data timestamp and `grounded: true`.
  - `make ask Q="Compare the Championship playoff format with the Bundesliga relegation playoff."` produced a
    two-note synthesis with both `Source:` citations.
  - Unit: `tests/test_complex_path.py` covers the planner allowlist, the composer input, the verifier and both
    fallbacks; integration: two new end-to-end complex turns in `tests/integration/test_gateway_stack.py`.
  - `make test` 335 unit tests and `make itest` 37 integration tests pass; `make lint` clean.
  - The simple path still returns the deterministic answer and no Beam model in `model`.

### S13 — Close the scorer gap (2026-10-23, branch `anammari-m4-agent`)

- **Delegated:** investigate whether the top-scorer refusal was a paid-data limit and, if not, close it: a backend
  operation, a contract schema, an MCP tool, the router label, the composer and tests.
- **Finding:** not a paid-data limit. The `top_scorers` table held **5,583** rows, and the free key returned scorer
  totals on 2026-10-10 even though the pricing page advertises them as a paid feature. The gap was the missing
  endpoint/tool, not access.
- **Rejected or revised, and what made each visible:**
  - *Querying `top_scorers` directly from the MCP server.* Rejected: the MCP server is an adapter over the API;
    direct DB access would break the read-only path and the contract.
  - *A scorer tool with no competition.* The first live run resolved Haaland to the Champions League (first
    competition found) instead of the Premier League. Revised: a player-name lookup across competitions, preferring
    a domestic league, then the bigger tally. The live run then returned the Premier League table with Haaland first.
  - *Returning only the named player.* Kept the top-five list, because "who is top scorer" and "how many has X"
    both need the ranking; the named player is first when the lookup matched.
- **Evidence:**
  - Contract v0.3.0 adds `GET /competitions/{code}/top-scorers` (`TopScorersTable`, `TopScorer`); the backend and
    `openapi.yaml` versions moved together. Live endpoint returns PL, season 2026, snapshot 2026-10-22.
  - MCP `get_top_scorers` is tool 8; the router prompt has the label; the composer prints the ranking and timestamp.
  - `make ask Q="how many goals has Haaland scored this season?"` → `route: tool`, `get_top_scorers`, "Erling
    Haaland (Manchester City FC): 8 goals", snapshot timestamp, `grounded: true`.
  - `make test` 344 passed, `make itest` 38 passed, `make lint` clean.
  - The four `unsupported` scorer questions in the frozen M4 holdout predate the tool; they are recorded as
    historical labels, not re-run as a gate for this change.

### S14 — PR review findings: verifier strength and MCP token (2026-10-23, branch `anammari-m4-agent`)

- **Delegated:** none. A pull-request review raised two Medium findings; the coding agent reproduced and fixed both.
  The owner has since ruled that no agent may request Copilot reviews; this review arrived before that rule, and no
  further review was requested.
- **Reviewed and fixed:**
  - *Complex-answer grounding could be bypassed.* The verifier checked only that the draft carried a real date/source
    or a retrieved filename, so a fluent draft with a fabricated fact could pass. Added a focused second `beam:cloud`
    call (`prompts/0006-complex-verifier.md`) that sees the question, results and draft and returns
    `{"supported": true|false}`. A false or unparseable verdict falls back to the deterministic composer. The
    deterministic citation check stays as the cheaper first gate.
  - *A separate `MCP_SERVER_TOKEN` broke gateway calls.* The MCP server required it, but Compose passed only
    `API_AGENT_TOKEN` to `hermes`; the gateway then used the API token and failed authentication. `MCP_SERVER_TOKEN`
    is now passed to both `hermes` and the tests service, with the API token as the fallback when it is empty.
- **Also fixed while reproducing:** the complex `get_team_form` tool crashed on `TeamForm.matches[].competition`,
  which is a string, not an object. The tool now has a separate `_form_match` formatter. The live complex run now
  returns both standings and form and is verified.
- **Evidence:** `tests/test_complex_path.py` covers the verifier accept, reject and fallback; `make test`
  (347 unit), `make itest` (38) and `make lint` pass after the changes. Live `make ask` for the complex
  standings+form question returns a two-result Beam answer with `grounded: true`.

### S15 — High-severity PR review fixes (2026-10-23, branch `anammari-m4-agent`)

- **Delegated:** none. A pull-request review raised 18 findings, six High. The coding agent reproduced and fixed
  every High finding and the Medium findings that were real defects.
- **High findings fixed:**
  1. **Placeholder replacement reprocessed inserted user text.** `fill()` now substitutes once with a regex over
     the original template; a message containing `{{route}}` or `{{aggregate}}` is text, not a second substitution,
     and an unknown template placeholder fails before a model call.
  2. **Insert failures could log the conversation.** The writer engine now uses `hide_parameters=True`, so a
     SQLAlchemy exception cannot render the user message, answer or tool arguments into the gateway log.
  3. **The MCP adapter received database-owner credentials.** `mcp-server` no longer inherits `DATABASE_URL` or
     the owner role; it gets only `BACKEND_BASE_URL`, `API_AGENT_TOKEN` and `MCP_SERVER_TOKEN`. The gateway also
     lost the owner URL; its only database path is the insert-only writer.
  4. **The gateway lacked the configured MCP token.** `MCP_SERVER_TOKEN` is now passed to `hermes` and the tests
     service, so a distinct MCP token does not fall back to the API token.
  5. **Errored routing counted as a successful refusal.** The holdout scorer treats an errored decision as a missing
     prediction: it is not counted as correct and cannot pass a safety gate. A regression test pins it.
  6. **The UCL qualification note said domestic cups lead to the Champions League.** Corrected to domestic league
     places and the Champions League/Europa League titleholder routes; cup winners enter the Europa League or
     Conference League. The note was re-indexed.
- **Medium findings also fixed:** ordinary short club names such as Brighton resolve (ambiguity returns no team);
  a missing tool argument is a JSON-RPC invalid-params error, not HTTP 500; MCP handling is off the event loop;
  `SOUL.md` states the simple/complex egress boundary and no longer forbids the complex composer; the freshness
  answer labels the report generation time; the citation guard requires an explicit "As of" date **and time**;
  the tests service has the host-gateway mapping; the isolated harness starts `mcp-server`; the MCP integration
  test uses the MCP token; isolated data-dependent tests skip on an empty volume.
- **Evidence:** `make test` 352 passed, `make itest` 38 passed, `make lint` clean. Live checks: a message containing
  `{{route}}` answers normally; complex standings+form is Beam-composed and grounded; the scorer question returns
  the Premier League table; the corrected UCL note is retrievable. `make itest-isolated` could not be re-run here
  because buildx cannot write its activity file on this host; the isolated data/MCP changes are covered by the
  retained-stack suite and the skips.

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

`prompts/` is the versioned prompt bank (see its README). It holds
[`0001-m3-backend-api.md`](../prompts/0001-m3-backend-api.md), the task that produced `backend/`, and
[`0002-router-model-comparison.md`](../prompts/0002-router-model-comparison.md), the one routing request both models
received, so the model was the only variable. It is versioned with the run and referenced by decision 0003.
