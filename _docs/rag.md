# Notes the bot can search (RAG)

What the retrieval half of this bot is, what it is built from, and how we will measure whether it is any good.

The bot answers two kinds of question, and only one of them is a database question. If the answer is a number, a
date or a table — a score, a fixture, a league position — it comes from Postgres. If the answer is a *sentence*
someone wrote down — how a promotion playoff works, what "aggregate" means, why a score is ten minutes behind — it
comes from our own notes. Searching those notes is the "RAG" part of this project ([`scoping.md`](scoping.md) §4
explains the split, §5 why it earns its place).

Status: **built and working end to end.** M1–M3 built the storage, chunker, local embedder, indexer and retrieval
endpoint; M4 authored and reviewed thirteen notes, indexed 41 chunks, and wired retrieval into the Telegram agent
(simple top-hit and complex multi-passage synthesis). The retrieval quality scoreboard is M5.

## 1. Which milestone owns which part

| Part | Where it lives | Milestone | Status |
| --- | --- | --- | --- |
| Storage: `knowledge_chunks` with a `vector(768)` column, per-chunk model and dimension, content hash | `db/models.py`, [`0001_init.py`](../db/migrations/versions/0001_init.py) | M1 | Implemented |
| Chunking notes into passages with a heading and an ordinal | `ingest/knowledge/chunker.py` | M1 | Implemented |
| Embedding with a local model, document/query asymmetry, dimension probe | `ingest/knowledge/embedding.py`, [decision 0002](decisions/0002-embedding-model.md), [0004](decisions/0004-embedding-tag-mlx.md) | M1 | Implemented |
| Ingestion: hash each file, embed only what changed, delete what left the corpus | `ingest/knowledge/indexer.py`, `make index-notes` | M1 | Implemented |
| Manifest and its checks: a note without an entry, or an entry with no file or source, fails the build | `ingest/knowledge/manifest.py`, `make check-notes` | M1 | Implemented |
| Re-indexing changed notes on the daily schedule | `ingest/pipeline.py`, driven by `ingest/scheduler.py` | M2 | Implemented |
| The retrieval surface the bot calls | `backend/routers/knowledge.py` (`GET /search/knowledge`) | M3 | Implemented |
| **The notes themselves** — the knowledge being searched | `hermes/agent-knowledge/**/*.md` | **M4** | **13 reviewed notes, 41 chunks** |
| The agent that searches, answers from what it found, and cites the file and heading | `agent/gateway/`, `mcp_server/` | **M4** | Implemented — one top hit on the simple path; eight passages plus `beam:cloud` synthesis on the complex path |
| The scoreboard that turns retrieval quality into a number | `evals/`, `frontend/` | **M5** | Not started; the routing holdout is separate |
| Re-indexing in CI when a note changes, and a quality threshold on every pull request | `.github/workflows/` | **M6** | Not started |

Today the corpus holds thirteen reviewed notes across formats, tiebreakers, qualification/relegation, data policy,
coverage limits, glossary and multi-hop. The retained database holds **41 chunks from 13 files**, all
`embeddinggemma:300m`, all 768-dimensional.

## 2. Proof it works, not just that it exists

Run against the retained volume, with the real model:

```text
$ make search Q="how does the championship playoff work"
0.587  formats/championship-playoffs.md  ::  How the Championship promotion play-offs work
0.487  qualification_relegation/bundesliga-relegation.md  ::  Bundesliga promotion and relegation
0.448  formats/european-competitions.md  ::  The UEFA Champions League format
0.444  qualification_relegation/champions-league-qualification.md  ::  How clubs qualify for the Champions League
0.436  tiebreakers/serie-a-level-points.md  ::  Serie A tiebreakers
```

That is the whole path: note files, chunked, embedded locally, stored as `vector(768)`, searched by cosine
similarity, returned with source file and heading. The retained database agrees: **41 chunks, 13 source files,
`embeddinggemma:300m`, dimension 768**.

Tests that hold this in place: `tests/test_chunker.py`, `tests/test_indexer.py`, `tests/test_corpus_manifest.py`,
`tests/test_schema.py`, the retrieval cases in `tests/test_api_insights.py`, and `tests/integration/`
(`test_postgres_stack.py`, `test_ingestion_stack.py`, `test_backend_stack.py`) for the real Postgres and the real
model.

## 3. Technical specifications

### Framework: none, on purpose

There is **no RAG framework here — no LangChain, LlamaIndex, Haystack or vector-store SDK.** The pipeline is plain
Python: SQLAlchemy for the table, `pgvector` for the vector type and the distance operator, `httpx` for one HTTP
call to Ollama, PyYAML for the manifest. About 630 lines in `ingest/knowledge/` and 140 more in `backend/`.

That is a decision, not an oversight:

- The two things that must be exactly right are the **task prefixes** and the **vector width**, and a framework hides
  both behind a default. Here each is one named constant and one checked number.
- The corpus is a directory of Markdown files, the index is one table, and retrieval is one `ORDER BY` — there is
  nothing for an orchestration layer to orchestrate.
- Fewer dependencies is fewer things to audit when the security criterion asks what the bot can reach
  (`product-spec.md` §F10).
- The interface the agent uses is our own `openapi.yaml`, not a framework's Python API, so swapping the mechanism
  later cannot change the contract.

### Chunking

Implemented in `ingest/knowledge/chunker.py`; the numbers are module constants.

| Setting | Value | Why |
| --- | --- | --- |
| Split at | Markdown headings `#` to `####` | A note is written one topic per file with headings; a heading is the natural passage boundary and doubles as the citation |
| Heading of a passage | Nearest heading above it (`untitled` if none) | So a passage is never cited as "somewhere in the file" |
| `MAX_CHARS` | **1200** | Comfortably inside the model's context, and small enough that a retrieved passage is useful to put in front of a model (`KnowledgeHit.snippet` allows 1200) |
| Split when too long | At blank lines first; a single over-long paragraph is cut at the last space before the limit | Never cut mid-sentence unless one paragraph is itself larger than the limit |
| `MIN_CHARS` | **80** | Below this it is a label or a heading-only stub, not an answer |
| Overlap | **None** | Sections are self-contained, the heading travels with every chunk, and overlapping text would be counted twice in recall and repeated in the model's context |
| Determinism | Same file text always yields the same chunks in the same order | This is what lets a content hash decide staleness without asking a model (`R-F6.4`) |

### Embedding

| Setting | Value |
| --- | --- |
| Model | `embeddinggemma:300m`, served locally by the `ollama` container (CPU-only derived image, 637 MB — [decision 0005](decisions/0005-ollama-image.md)) |
| Dimensions | **768**, pinned in the migration as `vector(768)`; probed at run time and checked on every write |
| Document format | `title: {title} \| text: {text}` |
| Query format | `task: search result \| query: {query}` |
| Normalisation | L2, so cosine distance and inner product agree and the index's operator class is not the only thing deciding what "closest" means |
| Transport | One `POST /api/embed` per file (all of that file's chunks in one request), 60 s timeout |
| Cost | Local, so embedding is free and nothing leaves the machine |

Two honest caveats, both written in the code rather than discovered later:

1. The prefixes are the convention seen in the model's usage documentation. They were **not** confirmed against the
   EmbeddingGemma model card, which we could not read in full. Fixing them is a one-line change plus
   `python -m ingest.knowledge index --force`, and M5 is where a wrong prefix finally shows up as a number.
2. Every chunk stores `embedding_model` and `embedding_dim`, so changing either is a **detectable re-index** rather
   than a silently mixed vector space.

### Storage

- One table, `knowledge_chunks`: `id`, `source_file`, `heading`, `ordinal`, `chunk_text`, `embedding vector(768)`,
  `embedding_model`, `embedding_dim`, `content_hash`, `updated_at` (+ `created_at`). The row maps to the contract's
  `KnowledgeHit`; the mapping is in [`data-model.md`](data-model.md).
- Index: **HNSW** with `vector_cosine_ops` (`ix_knowledge_chunks_embedding_hnsw`), plus a B-tree on `source_file` for
  the per-file replace. HNSW because the corpus is read on every knowledge question and 768 dimensions is well inside
  pgvector's index limit.
- **The Markdown files are the source of truth; the table is a derived index** and can always be rebuilt from the
  files. Nothing writes prose into the database, and nothing generates notes at run time.
- Postgres 16 + pgvector in the stack; SQLite is the development fallback and scores in Python, same answer, slower.

### Ingestion and re-indexing

- `python -m ingest.knowledge index` (`make index-notes`) reconciles the index with the corpus; `--force` re-embeds
  regardless and `--only FILE` restricts the run to one note while writing it; `python -m ingest.knowledge check`
  (`make check-notes`) only validates the corpus against the manifest, and `python -m ingest.knowledge search "..."`
  (`make search Q="..."`) is the command whose output is quoted in §2.
- **Staleness is a hash, not a model call**: SHA-256 of the whole source file is compared with the stored
  `content_hash`. An unchanged file is not re-embedded, so a second run writes nothing.
- A changed file is replaced wholesale (delete that file's chunks, insert the new ones) in one transaction; a file
  that leaves the manifest is deleted from the index; a note marked `retired` keeps its manifest entry and loses its
  chunks.
- The width is verified on write: a vector that is not exactly `vector(768)`, or a model whose `dim` disagrees with
  the schema, raises instead of storing something the index cannot use.
- Runs on the ingest schedule (M2), and will run in CI when a note changes (M6).

### Retrieval

`GET /search/knowledge` (`operationId: searchKnowledge`), implemented in `backend/services/knowledge.py`.

| Parameter | Contract | Meaning |
| --- | --- | --- |
| `q` | 2–300 characters, required | The question, embedded with the query prefix |
| `k` | 1–10, default 4 | Passages returned |
| `competition` | a `CompetitionCode` | Boosts passages whose note is tagged with that competition |
| `minScore` | 0–1, default 0.3 | Hits below it are **dropped, not padded** |

- Ranking: pull a pool of **30** (`PASSAGE_POOL`, wider than `k` so the boost can lift a passage similarity alone
  would rank lower), add **0.05** (`COMPETITION_BOOST`) when the note is tagged with the requested competition, then
  apply the threshold, then take the top `k`. The boost is a tie-breaker: because the threshold is applied *after*
  it, a boost cannot keep an irrelevant passage alive on its own.
- The score is clamped to `0..1` **before** the threshold, so `minScore=0` keeps the hits it means to keep (a raw
  cosine can be negative on the SQLite path).
- An empty `data` array is a normal, meaningful answer: *the corpus does not cover this*. The agent must be able to
  say so rather than have the endpoint pad a reply to look helpful.
- Each hit carries `chunk_id`, `source_file`, `heading`, `snippet` (≤ 1200 chars), `score` and `updated_at`. The
  citation the agent quotes is therefore a field it was handed, not something it has to remember.
- `data_as_of` is `null`: a note has no upstream timestamp, and the contract says so for derived data.
- A broken or missing manifest disables the competition boost and logs a warning — **a corpus problem must not become
  a retrieval outage**. `make check-notes` is where that gets fixed.

### How the agent uses retrieval in M4

- **Simple knowledge question:** `clef:cloud` picks `knowledge`; the gateway calls `search_knowledge` with `k=3` and
  the deterministic composer quotes the top passage with `Source: <public note URL> (<heading>)`.
- **Complex knowledge question:** the gateway calls `search_knowledge` with `k=8`, then `beam:cloud` synthesises
  across the passages. A citation check and a focused second-model claim check run before the answer is sent; a
  failure falls back to the top passage.
- Every turn records `route`, `route_source`, `route_confidence` and `grounded`, so retrieval and generation are
  visible separately in `agent_turns`.

### The corpus and its manifest

- Notes live in `hermes/agent-knowledge/**/*.md`, English, one topic per file, named `<class>/<slug>.md`.
- The corpus is mounted **read-only** (`:ro`) into every container that reads it — `backend`, `ingest`, `migrate`,
  `tests` and `hermes` (product-spec §4). A test reads the Compose file and fails if any mount of
  the corpus is writable, because a read-only corpus is what makes "the notes are the source of truth" a property
  rather than a promise.
- `hermes/agent-knowledge/manifest.yaml` (version 1) lists every note with `file`, `title`, `question_classes`,
  `competitions`, `source`, `owner`, `status` and `reviewed_at`. The same keys appear as YAML front-matter in the
  note, and the checker compares the two copies.
- `question_classes` are the seven classes of [`scoping.md`](scoping.md) §4: formats, tiebreakers,
  qualification_relegation, data_policy, coverage_limits, glossary, multi_hop.
- `status` is `draft`, `reviewed` or `retired`. **Drafts are indexed**, so the pipeline can be exercised before the
  corpus is finished; M4 finished with all thirteen notes `reviewed`.
- The check fails on: a file on disk that is not listed, an entry with no file, an entry with no source, a duplicate
  entry, a path that escapes the corpus, an unknown or empty `question_classes`, a bad `status`, or a missing
  `reviewed_at`.

## 4. The notes are written by hand, not by a model

This is worth stating because "RAG" projects often generate their corpus. Here the opposite is a hard rule
([`AGENTS.md`](../AGENTS.md) rule 9, [`product-spec.md`](product-spec.md) `R-F6.1a`): notes are **hand-written from
stable public sources** —
competition regulations, the provider's own documentation — versioned in git, changed through pull requests, and
**reviewed like code**. They are never generated at run time and never scraped, and upstream API payloads are not a
source of prose: they carry no sentences to quote. A model *embeds* the notes; a model does not write them.

M4 finished that work: thirteen notes across the planned classes, each with a checked source URL
([`notes-sources.md`](notes-sources.md)), a citation, an owner and a review date. The remaining work is evaluation
(M5), not authoring: the corpus is small enough that a full re-index is cheap, which is why it stays deliberate.

## 5. How we will evaluate the retrieval — the proposal

M4 added a runtime claim verifier on the complex path; the scoreboard below is still M5. A wrong answer has two possible
causes: the retriever handed over poor passages, or the generator ignored good ones. Measuring only the final answer
cannot tell them apart, so we score retrieval and generation separately and then read the pattern.

Four dimensions, in the order the pipeline runs:

1. **Context relevance — did the retriever bring back useful passages?**
   - *Per question:* judge each retrieved passage on its own ("does this passage help answer this question?") against
     the question, then average.
   - *Reported as:* the share of the top-`k` passages judged relevant, plus the mean similarity score.
   - *A low score means:* retrieval noise — the model is being handed text that will distract it. Look first at
     chunking (passages too small or mixing topics), then at the task prefixes, then at `minScore`.
   - *Cheap deterministic part first:* did the hit's `source_file` and `heading` exist in the corpus? Is the score
     above the threshold? Both are already fields, so neither needs a judge.

2. **Context recall — did the retriever find everything it needed?**
   - *Needs ground truth:* each rules question in the golden set is annotated by hand with the note(s) and
     heading(s) that should answer it. That annotation is part of `evals/` (M5, `R-F9.1`, which already requires an
     expected route per question — this extends it to the expected passage).
   - *Reported as:* the share of expected passages that appear in the top-`k`.
   - *A low score means:* we missed a passage that existed — usually because `k` is too small, or because the note
     that should answer the question is too thin to match on its own. High relevance with low recall is the
     signature: good passages found, not enough of them.
   - *Also:* the multi-hop questions in [`scoping.md`](scoping.md) §4 ("fifth place and wins the cup") need two
     notes at once, so they are the honest test of this dimension.

3. **Faithfulness — is every claim in the answer supported by what was retrieved?**
   - *This is the most important one, because it is the hallucination measure.* Extract the factual claims from the
     answer, check each one against the retrieved passages, and report the percentage supported.
   - *In this project it has a second use:* every turn records `grounded`, described in the contract as *computed by
     the answer-verifier, not self-reported by the answering model*. Scoring faithfulness independently is how we
     check the verifier itself rather than trusting it.
   - *A low score means:* the answer went beyond its evidence. With high relevance it means the generator ignored the
     context — a prompt problem, not a retrieval problem. With low relevance it means the retriever failed first.

4. **Answer completeness — does the answer cover the whole question?**
   - *Per question:* list the aspects the question asks for (a multi-part question has several), then check which are
     addressed and name the missing ones.
   - *A low score means:* correct but incomplete — the failure that looks fine and still sends the user away without
     an answer. It is scored separately precisely because a faithful answer can be incomplete.

### Reading the four together

| Pattern | Diagnosis |
| --- | --- |
| Low relevance + low faithfulness | The retriever returned poor context **and** the generator invented things on top of it. Fix retrieval first; the generator may improve with it. |
| High relevance + low faithfulness | Retrieval was fine and the generator ignored it. A prompt and grounding problem. |
| High relevance + high faithfulness + low completeness | Correct but incomplete. The prompt stops short, or the retrieved passage was too small to contain the whole answer. |
| Low recall + high relevance | Good passages found, required ones missed. Raise `k`, or fix the note that should have matched. |

### How we avoid fooling ourselves

- **A model-based judge is validated before its numbers count.** `R-F9.2` already says any model judgement —
  including a routing judge — must be checked against hand-labelled cases first. The same applies here: a judge
  that cannot reliably spot a deliberately unsupported claim is not allowed to produce the faithfulness number.
- **Deliberate failures are planted.** Following the acceptance criteria already written for the harness
  ([`product-spec.md`](product-spec.md) §F9: a deliberately wrong answer is caught, and a wrong route is caught as a
  routing failure rather than as a wrong answer), the RAG scoring gets a seeded bad answer and a seeded bad retrieval
  and must fail on each.
- **Deterministic checks run before the judge** so the judge only judges what cannot be checked mechanically:
  citation present, cited file exists, cited heading exists, score above the threshold.
- **Every number is reproducible**: the golden set is a file, the model is pinned, the embeddings are local, and a
  run produces a machine-readable report.
- **The same four dimensions are computable on real traffic**, not just the golden set: `agent_turns` already stores
  the route, the tool calls and whether the answer was grounded, so the dashboard can show a trend.

### Where the numbers will show up

- `evals/` — the golden set with its expected passages and routes, the scoring code, and a machine-readable report
  (M5).
- `frontend/` — the dashboard's eval view, including a retrieval slice, so a regression is visible over time (M5).
- `.github/workflows/` — retrieval and groundedness thresholds as a check on pull requests, with the corpus
  re-indexed whenever a note changes (M6).
- `_docs/ai-usage-report.md` — what the evaluation found and what was changed because of it.

### Cost and honesty

Every number above is produced with local models, so the evaluation costs no API money and can run on every change.
The trade-off is real and worth writing down: a small local judge is a weaker judge than a frontier model, which is
exactly why the judge is validated against hand-labelled cases before it is trusted, and why the deterministic checks
carry as much of the load as possible.

## 6. Where to look next

- The split between database answers and note answers: [`scoping.md`](scoping.md) §4, and why retrieval is extra work
  worth doing in §5.
- The requirements this implements: [`product-spec.md`](product-spec.md) §F6 (corpus and retrieval) and §F9
  (evaluation harness).
- The decisions behind it: [0001](decisions/0001-notes-corpus-manifest.md) (the corpus and its manifest as the source
  of truth), [0002](decisions/0002-embedding-model.md) (why this embedding model), [0004](decisions/0004-embedding-tag-mlx.md)
  (the tag that runs in the container), [0005](decisions/0005-ollama-image.md) (the derived model server).
- The tables and their mapping to the contract: [`data-model.md`](data-model.md).
