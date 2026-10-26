# Notes and retrieval (RAG)

How the bot answers written-rule questions, and how retrieval is built and checked. The split between database and
notes is in [`scoping.md`](scoping.md) §3.

Status: **working end to end.** Thirteen reviewed notes, 41 chunks in pgvector, simple top-hit answers and complex
multi-passage synthesis in Telegram. The retrieval scoreboard is still M5.

## 1. What owns what

| Part | Where | Status |
| --- | --- | --- |
| `knowledge_chunks` table, `vector(768)`, per-chunk model/dim/hash | `db/models.py`, migration `0001_init` | Built |
| Heading chunker | `ingest/knowledge/chunker.py` | Built |
| Local embedder with document/query prefixes and width probe | `ingest/knowledge/embedding.py` | Built |
| Hash-based re-index, delete retired/removed notes | `ingest/knowledge/indexer.py`, `make index-notes` | Built |
| Manifest and checks | `ingest/knowledge/manifest.py`, `make check-notes` | Built |
| Daily re-index on the ingest schedule | `ingest/pipeline.py`, `scheduler.py` | Built |
| Retrieval API | `backend/routers/knowledge.py` (`GET /search/knowledge`) | Built |
| 13 reviewed notes | `hermes/agent-knowledge/**/*.md` | Built, 41 chunks |
| Agent use: simple top hit; complex 8 passages + `beam:cloud` | `agent/gateway/`, `mcp_server/` | Built |
| Retrieval scoreboard | `evals/`, `frontend/` | M5 |

Current corpus: 13 files, 41 chunks, all `embeddinggemma:300m`, 768 dimensions.

## 2. Proof

```text
$ make search Q="how does the championship playoff work"
0.587  formats/championship-playoffs.md  ::  How the Championship promotion play-offs work
0.487  qualification_relegation/bundesliga-relegation.md  ::  Bundesliga promotion and relegation
0.448  formats/european-competitions.md  ::  The UEFA Champions League format
0.444  qualification_relegation/champions-league-qualification.md  ::  How clubs qualify for the Champions League
0.436  tiebreakers/serie-a-level-points.md  ::  Serie A tiebreakers
```

That is the path: Markdown file → heading chunks → local embed → `vector(768)` → cosine search → file, heading, snippet.
The retained database agrees: 41 chunks, 13 files, `embeddinggemma:300m`, 768 dimensions.

## 3. How it works

**No RAG framework.** Plain Python: SQLAlchemy table, pgvector type and distance, one `httpx` call to Ollama, PyYAML
manifest. The two things that must be exact — task prefixes and vector width — stay visible as named constants.

**Chunking.** Split at Markdown headings; nearest heading is the citation; `MAX_CHARS=1200`, `MIN_CHARS=80`; no
overlap; same text yields same chunks.

**Embedding.** `embeddinggemma:300m`, local, 768-d, L2-normalised. Documents: `title: … | text: …`; queries:
`task: search result | query: …`. Stored per chunk: model and dimension, so a change is a detectable re-index.

**Storage.** One table, HNSW index with `vector_cosine_ops`, B-tree on `source_file`. Markdown is the source of truth;
the table is a derived index. Postgres 16 + pgvector; SQLite is a dev fallback that scores in Python.

**Ingestion.** SHA-256 of the file decides staleness; a changed file is replaced wholesale; a removed note is
deleted; a `retired` note keeps its manifest entry and loses chunks. Width mismatch raises, never stores a mixed
vector space.

**Retrieval.** `GET /search/knowledge`, `q`, `k` (default 4), optional competition boost and `minScore` (default 0.3).
Pull 30 passages, add 0.05 for a matching competition tag, threshold, take top `k`. Empty `data` means "not covered",
never padded. `data_as_of` is null: notes carry no upstream timestamp.

## 4. How the agent uses it

- **Simple knowledge question:** `search_knowledge` with `k=3`, deterministic composer quotes the top passage.
- **Complex knowledge question:** `search_knowledge` with `k=8`; `beam:cloud` synthesises across passages; citation
  check and second-model claim check; fallback to the top passage.
- **Citations are public:** `PUBLIC_NOTES_BASE_URL` builds a GitHub blob URL pinned to `m4-review`; a model that prints
  a file name is rewritten to the URL. The note page carries its official source links.
- Every turn records route, source, confidence and `grounded`.

## 5. Corpus rules

- English, one topic per file, `<class>/<slug>.md`.
- Hand-written from stable public sources; never generated at runtime, never scraped.
- Manifest lists file, title, classes, competitions, source, owner, status, reviewed date; front-matter must match.
- `make check-notes` fails on an undeclared file, missing file, missing source, duplicate, escaping path, bad class or
  status.
- Corpus is mounted read-only in `backend`, `ingest`, `migrate`, `tests` and `hermes`.

## 6. How retrieval is scored

These are the four dimensions of `_docs/rag.md`, as they ship in M5 (`evals/golden/`), all deterministic:

1. **Context relevance / recall:** `recall@k` is the share of `expected_notes` that appear in the passages the answer
   was actually grounded on; `heading_recall` is the same for the expected headings. Both come from the golden set,
   not from a model's opinion.
2. **Faithfulness:** every knowledge answer must carry a `Source:` line, and every database answer its timestamp and
   source; the runtime verifier is the first guard, and the eval reports the `grounded` flag it sets. There is **no
   model judge** in M5, so there is no judge-human agreement to report - a judge would need its own hand-labelled
   validation and a new egress decision, and neither was signed off.
3. **Completeness:** `fact_coverage`, the share of the question's required term groups present in the answer. For
   knowledge questions the terms are the rule's own keywords; for tool questions they are only the entity names a
   correct answer must mention, never a value (a position or a score depends on the state of the table).
4. **Citations:** coverage of the composer's own lines, which makes a missing timestamp a composer regression rather
   than a model mood.

Seeded bad retrieval and bad answer must both fail: `make eval-self-check` scores a synthetic perfect run, then three
tampered ones, and exits non-zero if any tamper passes. Every run is reproducible from the golden file, the pinned
model and the local index, and the run stores the set hash and the commit.

## 7. Where to look

- Notes: `hermes/agent-knowledge/`
- Sources: [`notes-sources.md`](notes-sources.md)
- Indexer: `ingest/knowledge/`
- API: `backend/services/knowledge.py`
- Agent use: [`setup-and-review.md`](setup-and-review.md)
- Decisions: 0001 corpus, 0002/0004 embeddings
