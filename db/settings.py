"""One place where the environment is read.

Everything else in the codebase takes a `Settings` object, so a test can build one without touching
the environment (and so no module reaches for `os.environ` behind your back).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Dev default: a file SQLite database, so `make test` and a bare `python -m ...` work with no
# Postgres and no network. Compose always passes an explicit DATABASE_URL.
DEV_DATABASE_URL = "sqlite+pysqlite:///./data/hermes.db"


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = DEV_DATABASE_URL
    knowledge_dir: Path = REPO_ROOT / "hermes" / "agent-knowledge"
    ollama_host: str = "http://localhost:11434"
    embedding_model: str = "embeddinggemma:300m"
    embedding_dim: int = 768
    agent_db_role: str = "agent_readonly"
    agent_db_password: str | None = None
    upstream_base_url: str = "https://api.football-data.org/v4"
    upstream_api_key: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        knowledge_dir = Path(source.get("KNOWLEDGE_DIR") or REPO_ROOT / "hermes" / "agent-knowledge")
        if not knowledge_dir.is_absolute():
            knowledge_dir = REPO_ROOT / knowledge_dir
        return cls(
            database_url=source.get("DATABASE_URL") or DEV_DATABASE_URL,
            knowledge_dir=knowledge_dir,
            ollama_host=source.get("OLLAMA_HOST") or "http://localhost:11434",
            embedding_model=source.get("OLLAMA_EMBED_MODEL") or "embeddinggemma:300m",
            embedding_dim=int(source.get("OLLAMA_EMBED_DIM") or 768),
            agent_db_role=source.get("AGENT_DB_ROLE") or "agent_readonly",
            agent_db_password=source.get("AGENT_DB_PASSWORD"),
            upstream_base_url=source.get("UPSTREAM_BASE_URL") or "https://api.football-data.org/v4",
            upstream_api_key=source.get("UPSTREAM_API_KEY"),
        )

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")
