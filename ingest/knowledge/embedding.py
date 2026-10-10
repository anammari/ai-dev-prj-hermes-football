"""Embedding client: the only place that knows how to talk to Ollama.

`R-F6.2` puts two obligations here. First, the task prefixes: EmbeddingGemma is trained with
lightweight instruction prefixes and expects documents and queries to be formatted differently, so
the asymmetry lives in this module and nowhere else. Second, the dimension: `probe_dimension()`
reports what the provider actually returns, and the test suite fails if it disagrees with the
`vector(768)` the migration pinned (`_docs/decisions/0002`).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Protocol

import httpx

# --- Task prefixes ------------------------------------------------------------------------------
# WARNING: these strings are the EmbeddingGemma convention seen in the model's usage docs, but they
# have NOT been confirmed against the EmbeddingGemma 2 model card, which this project could not read
# in full. They are deliberately one constant each: confirming them is a one-line change followed by
# `python -m ingest.knowledge index --force`. Retrieval quality is scored in M5, which is where a
# wrong prefix would finally show up as a number.
DOCUMENT_PREFIX = "title: {title} | text: {text}"
QUERY_PREFIX = "task: search result | query: {query}"


class Embedder(Protocol):
    """What the indexer and the search path need from an embedding provider."""

    model: str
    dim: int

    def embed_documents(self, texts: Sequence[str], *, titles: Sequence[str] | None = None) -> list[list[float]]: ...

    def embed_query(self, query: str) -> list[float]: ...


def _normalise(vector: Sequence[float]) -> list[float]:
    """L2-normalise, so cosine distance and inner product agree and the HNSW index's operator class
    is not the only thing deciding what "closest" means."""
    norm = math.sqrt(sum(float(value) ** 2 for value in vector))
    if norm == 0:
        return [float(value) for value in vector]
    return [float(value) / norm for value in vector]


class OllamaEmbedder:
    """Ollama's `/api/embed`, with the corpus's document/query asymmetry applied."""

    def __init__(
        self,
        *,
        host: str,
        model: str,
        dim: int,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.dim = dim
        self._host = host.rstrip("/")
        self._client = httpx.Client(base_url=self._host, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OllamaEmbedder:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _embed(self, inputs: Sequence[str]) -> list[list[float]]:
        response = self._client.post("/api/embed", json={"model": self.model, "input": list(inputs)})
        response.raise_for_status()
        payload = response.json()
        vectors = payload.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(inputs):
            raise RuntimeError(f"unexpected /api/embed response from {self.model}: {payload.keys()}")
        return [_normalise(vector) for vector in vectors]

    def embed_documents(self, texts: Sequence[str], *, titles: Sequence[str] | None = None) -> list[list[float]]:
        labels = list(titles) if titles is not None else [""] * len(texts)
        if len(labels) != len(texts):
            raise ValueError("titles and texts must be the same length")
        return self._embed(
            [DOCUMENT_PREFIX.format(title=title, text=text) for title, text in zip(labels, texts, strict=True)]
        )

    def embed_query(self, query: str) -> list[float]:
        return self._embed([QUERY_PREFIX.format(query=query)])[0]

    def probe_dimension(self) -> int:
        """Ask the provider for one vector and report its width."""
        return len(self._embed(["dimension probe"])[0])

    def available_models(self) -> list[str]:
        response = self._client.get("/api/tags")
        response.raise_for_status()
        return [entry.get("name", "") for entry in response.json().get("models", [])]


class FakeEmbedder:
    """Deterministic embeddings for tests: no network, no model, stable across runs.

    Not a similarity model - it maps text to a reproducible pseudorandom direction, which is all the
    indexer tests need. Retrieval *quality* is measured against the real model, in M5.
    """

    def __init__(self, *, model: str = "fake-embedder", dim: int = 768) -> None:
        self.model = model
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [(digest[index % len(digest)] / 255.0) - 0.5 for index in range(self.dim)]
        return _normalise(raw)

    def embed_documents(self, texts: Sequence[str], *, titles: Sequence[str] | None = None) -> list[list[float]]:
        labels = list(titles) if titles is not None else [""] * len(texts)
        return [
            self._vector(DOCUMENT_PREFIX.format(title=title, text=text))
            for title, text in zip(labels, texts, strict=True)
        ]

    def embed_query(self, query: str) -> list[float]:
        return self._vector(QUERY_PREFIX.format(query=query))
