# Handoff — relocate the M2 branch to the project root, then fix the M2 review findings

> **What this file is.** A handoff prompt for the coding session that owns
> `/Users/ahmadammari/GitHub/ai-dev-prj-hermes-football`. Work through it top to bottom; Task 0 must
> finish before any code changes. Delete this file once Tasks 0–6 have landed (or keep it as a record
> of the review — your call).

## Corrections applied to the original instruction

Two deliberate deviations, both to protect the work rather than change the intent:

1. **"M32 branch" is read as the M2 branch**, `anammari-m2-ingest-pipeline`. That is the only branch
   matching the description — it is the one checked out in `anammari-didactic-tribble`.
2. **The thing to delete is the *worktree directory*, not the *branch*.** The request said to delete
   "the branch created in `~/GitHub/copilot-worktrees/…`". Deleting the *branch* would destroy exactly
   the work being secured, so Task 0 removes the worktree and explicitly forbids `git branch -D`.
   The branch must survive and end up checked out at the project root.

---

# Task: relocate the M2 branch to the project root, then fix the M2 review findings

## Context

- **Project root (the only working copy):** `/Users/ahmadammari/GitHub/ai-dev-prj-hermes-football`
- **Milestone branch:** `anammari-m2-ingest-pipeline`, tip `efea949` ("Update milestone tracker to mark
  M2 done"), parent `6ad15e7` ("Build the M2 ingestion pipeline"), merge-base with `main` = `8c9760f`.
- The branch is currently checked out in a **git worktree** at
  `~/GitHub/copilot-worktrees/ai-dev-prj-hermes-football/anammari-didactic-tribble`.
- The root is currently on `main` (`8c9760f`).
- Read `AGENTS.md` first and obey its hard rules. Do not merge to `main` in this task; `main` stays
  untouched.

**All work in this task — the relocation, the code fixes, the tests and the docs — is committed to
`anammari-m2-ingest-pipeline`.** No M2 implementation work goes on `main`.

---

## Task 0 — Relocate the worktree (do this FIRST, before touching any code)

Goal: exactly one working copy of this project, at the root, on the M2 branch, with the old worktree gone.

### 0.1 Pre-flight (prove nothing is lost)

1. In the worktree: confirm it is clean and capture the tip.
   ```bash
   cd ~/GitHub/copilot-worktrees/ai-dev-prj-hermes-football/anammari-didactic-tribble
   git status --porcelain          # must be empty
   git rev-parse HEAD              # record this (expect efea949…); call it <TIP>
   git status --porcelain --ignored   # LIST THIS AND REPORT IT
   ```
   Ignored files (`.env`, `.venv`, caches) do not block `git worktree remove` and **will be deleted with
   the directory**, so confirm nothing ignored is worth keeping before step 0.2.
2. Confirm the root `.env` is the good one — it holds the real `UPSTREAM_API_KEY` and the
   `POSTGRES_PASSWORD` the retained Docker volume was initialised with. Compare key names only, never
   print secret values:
   ```bash
   grep -oE '^[A-Z_]+' ~/GitHub/ai-dev-prj-hermes-football/.env
   ```
   Verify `UPSTREAM_API_KEY` there is **not** the `replace-with-…` placeholder.
3. At the root: confirm clean and on `main`.
   ```bash
   cd /Users/ahmadammari/GitHub/ai-dev-prj-hermes-football
   git status --porcelain              # empty
   git rev-parse --abbrev-ref HEAD     # main
   ```

### 0.2 Release the branch from the worktree

The branch lives in the shared object store and is already safe — **you are removing a *worktree* (a
directory), never a *branch*.**

```bash
git worktree list
git worktree remove ~/GitHub/copilot-worktrees/ai-dev-prj-hermes-football/anammari-didactic-tribble
```

Only if it refuses because of build artefacts: inspect what it objects to, then use `--force` **only
after** confirming there is nothing uncommitted that matters.

### 0.3 Check the branch out at the root so it becomes the active branch

```bash
cd /Users/ahmadammari/GitHub/ai-dev-prj-hermes-football
git checkout anammari-m2-ingest-pipeline
```

Verify:

- `git rev-parse HEAD` → must equal `<TIP>` exactly
- `git rev-parse --abbrev-ref HEAD` → `anammari-m2-ingest-pipeline`
- `git status --porcelain` → empty
- `git log --oneline -3` → `efea949 Update milestone tracker to mark M2 done`, then
  `6ad15e7 Build the M2 ingestion pipeline`
- The M2 files are present at the root: `ingest/pipeline.py`, `ingest/client.py`, `ingest/normalize.py`,
  `db/migrations/versions/0002_ingestion_storage.py`

### 0.4 Clean up the old location

```bash
git worktree prune
```

- Confirm `git worktree list` shows only the project root.
- A detached-HEAD worktree
  `~/GitHub/copilot-worktrees/ai-dev-prj-hermes-football/copilot-prewarm-verbose-train` (at `8c9760f`)
  may still exist — **report it, do not delete it in this task** unless the user explicitly confirms.
- Remove the leftover directory if it still exists. Verify the resolved absolute path before running;
  never run this against an unverified or computed path:
  ```bash
  rm -rf ~/GitHub/copilot-worktrees/ai-dev-prj-hermes-football/anammari-didactic-tribble
  ```

### Task 0 hard constraints

- **Never run `git branch -D anammari-m2-ingest-pipeline`** and never delete the branch. Only the
  worktree directory is removed; the branch must survive, checked out at the root.
- Do **not** rebase, squash, amend, reset or force-push the branch. Preserve `efea949` exactly.
- Do **not** delete or reset the Docker volume `hermes-football_pgdata`.
- Commit the relocation as its own small commit before starting Task 1.

---

## Task 1 — Put the rule in `AGENTS.md` (mandatory)

Document, so no future session can repeat this:

- This project has **exactly one working copy**:
  `/Users/ahmadammari/GitHub/ai-dev-prj-hermes-football`. All milestone planning and implementation
  branches are created and checked out **there**.
- **Do not create or use `git worktree` copies** of this repo under `~/GitHub/copilot-worktrees/…` or
  anywhere else. If a worktree for this project exists, relocate it per Task 0 before working.
- **The active branch is the milestone branch** (e.g. `anammari-m2-ingest-pipeline`), **not `main`**.
  `main` receives merged milestone work only.
- Add a short, copy-pasteable block showing how to check where you are and how to return to root +
  milestone branch.
- Record **why** the rule exists: two checkouts of the same repo shared the Compose project name
  `hermes-football` and one Postgres volume while carrying different `.env` passwords, which broke
  `make up` and `make itest` with `FATAL: password authentication failed for user "hermes"`.

---

## Task 2 — Fix the critical live-run failure: a 404 aborts the entire run

**Reproduce first**, then fix.

Observed on a real run with a valid token:

```json
{"calls_used": 15, "duration_seconds": 95.6,
 "errors": [{"message": "upstream returned HTTP 404 for /competitions/EC/standings", "resource": "run"}],
 "status": "failed"}
```

Cause: `/competitions/EC/*` returns 404 — EC is the 2024 European Championship and the free tier
publishes no standings/scorers for it. `ingest/client.py` maps **403 → `DataNotAvailable`** (caught and
recorded as `partial`), but **404 falls through to the generic `UpstreamError`**, which escapes the
per-competition loop in `ingest/pipeline.py` and aborts the whole run — before `/matches` is ever
fetched and before notes are re-indexed. Because EC is permanently in the competition list, **this
fails every day**, so M2 can never complete a run.

Required behaviour:

- A 404 from an **optional** sub-resource (`/competitions/{code}/teams|standings|scorers`,
  `/teams/{id}`) is recorded as an unavailable resource, exactly like a 403, and must **not** fail the
  run.
- **A failure for one competition must never abort the others.** Wrap each competition's body so any
  `UpstreamError` degrades that competition only and leaves the run `partial`.
- `"failed"` stays reserved for genuinely fatal conditions: the `/competitions` catalog failing, or a
  database/session error.
- Record which competitions were skipped and why in `IngestRun.errors`, keeping the existing
  `{"resource": …, "message": …}` shape.
- If the distinction matters for messages, add a distinct `ResourceNotFound(UpstreamError)` with
  `status_code=404` rather than overloading `DataNotAvailable`.

Acceptance: `make ingest` with a valid token completes end to end with `status` `succeeded` or
`partial` — never `failed` because of EC — `/matches` rows land, `notes_index` is populated, and
`calls_used`/`duration_seconds` are recorded.

---

## Task 3 — Regression tests for the fault-isolation fix

- A stub client returning **404** for `/competitions/TST/standings` → run is `partial`, other
  competitions are still ingested, `/matches` is still fetched.
- One competition raising a generic `UpstreamError` mid-way → the remaining competitions are still
  processed; run `partial`.
- The `/competitions` catalog itself failing → run `failed` (guard that boundary).
- Integration: keep the existing idempotency assertions and add a 404-competition path.
- The existing **44 unit** and **8 integration** tests must still pass.

---

## Task 4 — Remaining review findings

1. **Bronze retention.** `raw_payloads` grows unbounded — every page of every resource, every run,
   forever, with no pruning (the knowledge indexer prunes; bronze does not). ~300 rows/run ≈ ~110k JSON
   rows/year. Add a retention policy with a prune step, **or** write a decision record in
   `_docs/decisions/` justifying unbounded storage. Update `_docs/data-model.md` either way.
2. **`content_hash` is written on every bronze row but never read.** Either use it (skip writing an
   identical payload, or expose change detection) or document why it is stored. Don't leave it
   unexplained.
3. **Scheduler preflight.** `python -m ingest schedule` starts successfully with an invalid
   `UPSTREAM_API_KEY`, because the client and its key validation are built inside `action()`. Validate
   configuration at startup so `make up` fails loudly instead of surfacing a once-a-day logged
   exception.
4. **`RateLimiter.observe`.** When `x-requests-available-minute` is `0` but `X-RequestCounter-Reset` is
   absent, no block is applied. Handle that case deliberately.
5. **`measure_score_delay` calls `time.sleep` directly.** Make the sleep injectable like the rest of the
   codebase instead of monkeypatching stdlib in the test.
6. **Run duration / progress.** A successful full run needs roughly 250–350 upstream calls (≈30 min at
   10 req/min — the whole free-tier budget). Log progress per competition and document the expected
   duration and budget in `AGENTS.md` or `_docs/product-spec.md`.
7. **Compose project name.** Make it overridable — `name: ${COMPOSE_PROJECT_NAME:-hermes-football}` —
   so a future worktree can namespace its own volume without clobbering the default. **Keep
   `hermes-football` as the default** so the existing `hermes-football_pgdata` volume is preserved.
8. **Docs claim vs reality.** The docs say integration tests pass "against disposable Postgres";
   `make itest` actually runs against the retained stack DB. Either add a documented
   `make itest-isolated` target that boots a throwaway Postgres, or document the exact
   disposable-container command in `AGENTS.md`.

---

## Task 5 — Finish live M2 acceptance

The root `.env` already holds the working token **and** the password the retained volume was initialised
with, so both original blockers resolve once the branch lives at the root. Verify and finish:

- `make up` → must now apply `0002_ingestion_storage` with no authentication error.
- `make models`, `make test`, `make itest`, `make ingest`, `make score-delay`.
- Confirm `alembic_version` = `0002_ingestion_storage`.
- **Measure the real score delay** with `make score-delay` and write the number into
  `_docs/scoping.md` §3 and the delay policy in `_docs/product-spec.md`. It is currently "still
  unknown" — this is an outstanding M2 acceptance item.
- Never print secret values; never add `.env` to git.

---

## Task 6 — Make the docs match reality

- `AGENTS.md` — status, next steps, the root-location rule, expected run duration, the `make itest`
  caveat.
- `README.md` — milestone tracker. **M2 is not "Done"** until Tasks 2–5 pass; correct it.
- `_docs/ai-usage-report.md` — record this session: what was delegated, what you reviewed, what you
  rejected, and the tests that prove it. Replace the "verification pending" claims only once live
  acceptance genuinely passes.
- `_docs/data-model.md`, `_docs/product-spec.md` — any behaviour you changed.

---

## Working agreement (from `AGENTS.md` — follow it)

- Spec before code: change `_docs/product-spec.md` in the same PR as the behaviour change.
- One task per PR, small and reviewable; state goal + checkable acceptance criteria + out of scope.
- Verification is independent: whoever writes a feature does not sign it off.
- Commits: imperative subject; explain *why* in the body when it is not obvious.
- Keep the 14-criteria mapping in `_docs/scoping.md` true.
- Never log or commit secrets. Never hardcode the competition list. All upstream access goes through
  the ingest client.

---

## Report back with

1. Proof of relocation: `git worktree list`, `git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD`
   (must equal `<TIP>`), and confirmation the old
   `copilot-worktrees/…/anammari-didactic-tribble` path is gone.
2. The `AGENTS.md` diff for the root-location rule.
3. The fault-isolation diff plus the new tests.
4. Real `make ingest` output — `status`, `calls_used`, `duration_seconds`, `errors` — and the measured
   score delay.
5. Test results: unit and integration counts.
6. Anything you deliberately did **not** do, and why.
