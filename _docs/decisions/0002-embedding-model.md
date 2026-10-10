# 0002 — Embedding model: embeddinggemma-2:270m, local, 768 dimensions

- **Status:** Superseded by [0004](0004-embedding-tag-mlx.md) on 2026-10-10 — the family, the 768 width, the prefix rules
  and the re-index rules below all still stand; only the tag changed
- **Milestone:** M1 (provider, client, migration), M5 (retrieval quality)
- **Related:** `_docs/product-spec.md` R-F6.2, `_docs/scoping.md` §9

## Context

The spec said notes are "chunked and embedded into pgvector" but named no model, and the data model wrote
`embedding vector` with no dimension. Because pgvector pins the width (`vector(N)`), this decision blocked the first
Alembic migration, and M1's "a note file can be indexed end to end" needs a provider to call.

## Decision

**Default embedding model: `embeddinggemma-2:270m`, served locally by the `ollama` Compose service.**

Verified on the Ollama library page, 2026-10-10:

| Fact | Value |
| --- | --- |
| Family | EmbeddingGemma 2 (Google DeepMind), text/images/video/audio in one 768-d space, Gemma 4 architecture |
| Size | 740M total; the `270m` tag is the text-only variant (130M transformer + 140M embedder), 378 MB on disk |
| Native output dimension | **768** |
| Matryoshka truncation | 128 / 256 / 512 — 512 costs 1:1.5 storage, 256 costs 1:3, both with minimal quality loss |
| Context | 8,192 tokens per the model card (Ollama's list advertises 256K; trust the model card) |
| Languages | 100+ |
| Prefixes | Task-steered instruction prefixes: documents and queries must be formatted differently |

Rules that follow:

1. **`vector(768)` in the first migration**, with the width as one named constant, and a unit test asserting the
   provider's returned width equals the schema column.
2. **The client owns the task prefixes** (document versus query). Missing or wrong prefixes degrade retrieval
   silently, which is the expensive kind of wrong.
3. **The model is recorded, not assumed.** Each chunk stores `embedding_model` and `embedding_dim`, so swapping models
   is a detectable, re-runnable re-index of about ten files rather than a silently mixed vector space.
4. **Truncate only if storage ever matters.** 256d is the supported fallback (1:3); the default stays 768.
5. **Changing model, dimension or truncation is one migration plus one re-index**, never an in-place edit.

## Alternatives considered

- **`embeddinggemma:300m` (v1)** — works, 2K context, slightly worse on code and superseded by v2. No reason to start
  on the older generation. *(This is the alternative that turned out to be the only one that runs; see 0004.)*
- **A hosted embedding API** — would put note text and user questions on someone else's servers, against both the data
  policy (`R-F10.5`) and the free-tier cost target.
- **A larger variant of the same family** (`440m`/`570m`/`740m`) — bigger for modalities we do not use; the notes are
  text only.

## Consequences

- No per-call cost, no network dependency, note text never leaves the machine, one extra container and one more
  capability row.
- The embedding provider becomes part of M1 instead of a detail discovered later.
- Not checked at the time, and the reason this record is superseded: whether the tag can run in *our* container, as
  opposed to on the machine that read the library page.

## Verification

- M1 probe prints the returned vector length; the unit test fails if it differs from the schema width.
- M5: retrieval quality is scored on the golden set (correct file and heading returned), so a bad prefix or chunk size
  shows up as a number instead of as a strange answer.
