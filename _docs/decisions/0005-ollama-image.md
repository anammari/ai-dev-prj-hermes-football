# 0005 — The Ollama image: a flattened CPU-only build, because the CUDA trees cannot load here

- **Status:** Accepted (2026-10-13)
- **Milestone:** M2 (infrastructure); applies to M3–M6
- **Related:** `Dockerfile.ollama`, `docker-compose.yml`, `_docs/decisions/0004`, `AGENTS.md`

## Context

Every service that talks to a model ran the upstream `ollama/ollama:0.40.2`, which is **7.05 GB**. The bulk of it
is GPU backends this project cannot use: `/usr/lib/ollama` alone is 3.6 GB, being four CUDA trees — `cuda_v12`
(1.2 GB), `cuda_v13` (902 MB), `cuda_jetpack5` (842 MB) and `cuda_jetpack6` (635 MB).

The project runs in Docker Desktop on Apple Silicon, where a container has no NVIDIA GPU passthrough, so those
libraries can never be loaded. The CPU/ARM runners are what actually execute, and the live runs show it: an
embedding comes back in about a second.

## Decision

Build a derived image, `Dockerfile.ollama`, from the same pinned upstream tag:

1. delete the four CUDA trees, then
2. **flatten** the result into one layer with `FROM scratch` + `COPY --from`.

Step 2 is the one that matters. Deleting a file in a later layer removes it from the *filesystem* but leaves its
bytes in the layer below, so a plain `RUN rm -rf` would reclaim nothing. Flattening copies the cleaned filesystem
into a single new layer, which is what returns the space. `FROM scratch` also discards the upstream metadata, so
the ENV, EXPOSE, ENTRYPOINT and CMD are re-declared to match the pinned image, minus the NVIDIA variables that
only mean something with the NVIDIA container toolkit present.

`ollama` and `models` take the build from one Compose anchor, so the image is built once.

| | Upstream | `hermes-football-ollama:local` |
| --- | --- | --- |
| Reported size | 7.05 GB | **637 MB** |
| `/usr/lib/ollama` | 3.6 GB | 23 MB |
| CUDA trees | 4 | 0 |
| Ollama version | 0.40.2 | 0.40.2 (unchanged) |

## Alternatives considered

- **Keep the upstream image.** Simplest, and one `docker pull` away. Rejected: it spends about 6.4 GB on libraries
  this machine can never load.
- **`RUN rm -rf` in a thin layer on top.** The obvious approach, and it does not work — the bytes stay in the layer
  beneath. It would have looked like a fix while reclaiming nothing.
- **A community CPU-only Ollama image.** Off the pinned version and off Ollama's own build, so the version this
  project verified against would no longer be the version it runs. Rejected.
- **Run Ollama on the host's macOS instead.** Puts a component of the stack outside Compose and CI, which
  [0004](0004-embedding-tag-mlx.md) already rejected for the embedding tag.

## Consequences

- The stack depends on a build step for its model server, not only on a pull. Rebuilding re-pulls the upstream tag
  (~4.4 GB) once, because the flattened image no longer references it.
- **The image is CPU-only.** A machine with a real NVIDIA GPU gets no acceleration. That is correct for the stated
  environment; moving to a GPU host means pointing the Compose anchor back at `ollama/ollama:0.40.2`, which the
  header comment in `Dockerfile.ollama` says.
- The upstream `ollama/ollama:*` tags are no longer referenced by anything and were removed locally. They are
  re-pullable.
- The model itself is untouched: it lives in the `ollama-data` volume, and neither this change nor the tag removals
  go near it.

## Verification

- `docker run --rm hermes-football-ollama:local ollama --version` reports **0.40.2**.
- `tests/integration/test_postgres_stack.py::test_the_provider_returns_the_pinned_width` probes the width the
  container actually returns, and `::test_a_note_indexes_and_is_retrieved_through_ollama` indexes a note and
  retrieves it through Ollama. Both pass against the slim image, which is what shows the model server still does its
  job once the CUDA trees are gone.
- `docker compose logs ollama` is free of GPU and CUDA errors.
