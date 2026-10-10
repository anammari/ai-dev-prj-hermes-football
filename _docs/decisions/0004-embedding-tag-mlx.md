# 0004 — Embedding tag: embeddinggemma:300m, because the `-2` tag needs MLX

- **Status:** Accepted (2026-10-10)
- **Supersedes:** [0002](0002-embedding-model.md) — the family, the 768 width, the prefix rules and the re-index rules
  stand; the tag changes
- **Milestone:** M1 (provider, migration), M5 (retrieval quality)
- **Related:** `_docs/product-spec.md` R-F6.2, `_docs/decisions/0002`, `_docs/ai-usage-report.md`

## Context

0002 pinned `embeddinggemma-2:270m` after checking the Ollama library page. M1's integration test pulled that tag
inside the `ollama` Compose container and it refused to load it:

```text
Error: this model requires MLX support, but the MLX runtime is not available
```

The tag's Ollama manifest contains only `application/vnd.ollama.image.tensor` layers — Ollama's MLX/Safetensors
packaging — and MLX is an Apple-only runtime. The library page said nothing about it; the container did, immediately.
The alternative was to run inference on the host's macOS Ollama, which would put a component of the stack outside
Compose and outside CI.

## Decision

**Pin `embeddinggemma:300m`** (EmbeddingGemma v1, 308M parameters, 622 MB) as the default, still served by the
`ollama` Compose service, still 768 dimensions, so the schema, the migration and the client are unchanged.

Facts, split by how they were established:

| Fact | Value | How it was established |
| --- | --- | --- |
| Packaging | `application/vnd.ollama.image.model` (GGUF), runs on Linux | Ollama registry manifest, 2026-10-10 |
| Native output dimension | **768** | Probed in the `ollama` container, 2026-10-10 |
| Size | 308M parameters, 622 MB on disk including license and params blobs | Ollama registry manifest, 2026-10-10 |
| Context | 2K tokens | Model card as summarised by the library page |
| Matryoshka truncation | 512 / 256 / 128 | Model card as summarised by the library page |
| Prefixes | Task-steered instruction prefixes for documents and queries | Model card as summarised by the library page |

2K context is not a constraint here: the chunker caps a passage at 1,200 characters, so a passage and its heading sit
an order of magnitude inside the window. The exact prefix strings remain unverified (the model card pages truncate to
navigation when fetched), which is unchanged from 0002.

## Alternatives considered

- **`embeddinggemma-2:270m`** — dropped: MLX-only packaging, no Linux runtime.
- **`nomic-embed-text:latest`** — 274 MB, GGUF, also 768 dimensions, so a genuine drop-in that keeps `vector(768)`.
  Kept as the documented fallback if an EmbeddingGemma tag ever becomes unavailable or its licence becomes a problem.
- **`mxbai-embed-large`** — 1024 dimensions, so a different column and a migration for a corpus this small.
- **The host's macOS Ollama** — would make the stack's behaviour depend on the developer's laptop and put a component
  outside Compose, CI and the resource limits.

## Consequences

- The stack depends on a third-party tag's *packaging*, not only on its dimensions. `embedding_model` per chunk plus a
  single constant in `db/settings.py` means moving to `nomic-embed-text` is a re-index, not a redesign.
- A model that runs only on the developer's laptop is not a local-stack decision; it is a decision about the laptop.

## Verification

- `tests/integration/test_postgres_stack.py` fails when the pinned tag is missing from the `ollama` volume, and probes
  the width the container actually returns against `vector(768)`.
- `make models` pulls the tag from inside the Compose network, which is the only place the question "does it run here?"
  can be answered.
