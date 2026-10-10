"""Portable embedding column.

The full stack uses Postgres + pgvector, where the column is a real `vector(768)` and similarity
search is a database operation. The dev fallback is SQLite, which has no vector type, so the same
declaration compiles to TEXT holding the JSON array instead. `R-F2.3` asks for one code path on both
engines; this is that one path, and the search query is the only place that has to branch (see
`_docs/data-model.md`).
"""

from __future__ import annotations

import json
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

#: Native output width of the pinned embedding model. Pinned in the first migration as vector(768);
#: a probe test fails if the provider disagrees. See `_docs/decisions/0002`.
EMBEDDING_DIM = 768


class Embedding(TypeDecorator):
    """`vector(dim)` on Postgres, JSON text anywhere else."""

    impl = Text
    cache_ok = True
    #: pgvector's operators (`cosine_distance` and friends) are what `<=>` compiles from. Without this
    #: the column would be a Vector on Postgres but the query layer could not express a similarity
    #: search against it, and `ingest.knowledge.indexer` would have to import pgvector itself.
    comparator_factory = Vector.Comparator

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):  # noqa: ANN001, ANN201 - SQLAlchemy hook
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect):  # noqa: ANN001, ANN201 - SQLAlchemy hook
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps([float(x) for x in value])

    def process_result_value(self, value: Any, dialect):  # noqa: ANN001, ANN201 - SQLAlchemy hook
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.loads(value)
