"""Agent configuration, read once from the environment.

Kept separate from `db.settings.Settings` and `backend.settings.BackendSettings` because the gateway
is the only process that needs the router endpoint, the Telegram credentials and the write-only turn
log. Nothing here has a usable default for a secret: the gateway fails closed when one is missing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from db.settings import REPO_ROOT

DEFAULT_PROMPT = REPO_ROOT / "prompts" / "0003-agent-router.md"


def _ids(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    parsed = []
    for part in value.split(","):
        part = part.strip()
        if part:
            parsed.append(int(part))
    return tuple(parsed)


@dataclass(frozen=True, slots=True)
class AgentSettings:
    router_base_url: str = "http://host.docker.internal:11434"
    router_model: str = "clef:cloud"
    router_timeout: float = 20.0
    router_prompt: Path = DEFAULT_PROMPT
    planner_prompt: Path = REPO_ROOT / "prompts" / "0004-complex-planner.md"
    composer_prompt: Path = REPO_ROOT / "prompts" / "0005-complex-composer.md"
    composer_base_url: str = "http://host.docker.internal:11434"
    composer_model: str = "beam:cloud"
    composer_timeout: float = 90.0
    agent_turn_dsn: str | None = None
    chat_hash_salt: str | None = None
    telegram_bot_token: str | None = None
    telegram_allowed_users: tuple[int, ...] = ()
    telegram_admin_users: tuple[int, ...] = ()
    backend_base_url: str = "http://backend:8000"
    backend_token: str | None = None
    mcp_url: str = "http://mcp-server:8100/mcp"
    mcp_token: str | None = None
    mcp_timeout: float = 20.0
    poll_timeout: int = 30

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AgentSettings:
        source = os.environ if env is None else env
        prompt = Path(source.get("ROUTER_PROMPT") or DEFAULT_PROMPT)
        if not prompt.is_absolute():
            prompt = REPO_ROOT / prompt
        return cls(
            router_base_url=(source.get("ROUTER_BASE_URL") or "http://host.docker.internal:11434").rstrip("/"),
            router_model=source.get("ROUTER_MODEL") or "clef:cloud",
            router_timeout=float(source.get("ROUTER_TIMEOUT_SECONDS") or 20.0),
            router_prompt=prompt,
            planner_prompt=Path(source.get("PLANNER_PROMPT") or REPO_ROOT / "prompts" / "0004-complex-planner.md"),
            composer_prompt=Path(source.get("COMPOSER_PROMPT") or REPO_ROOT / "prompts" / "0005-complex-composer.md"),
            composer_base_url=(source.get("COMPOSER_BASE_URL") or source.get("ROUTER_BASE_URL") or "http://host.docker.internal:11434").rstrip("/"),
            composer_model=source.get("COMPOSER_MODEL") or "beam:cloud",
            composer_timeout=float(source.get("COMPOSER_TIMEOUT_SECONDS") or 90.0),
            agent_turn_dsn=source.get("AGENT_TURN_DSN") or None,
            chat_hash_salt=source.get("CHAT_HASH_SALT") or None,
            telegram_bot_token=source.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_allowed_users=_ids(source.get("TELEGRAM_ALLOWED_USERS")),
            telegram_admin_users=_ids(source.get("TELEGRAM_ADMIN_USERS")),
            backend_base_url=(source.get("BACKEND_BASE_URL") or "http://backend:8000").rstrip("/"),
            backend_token=source.get("API_AGENT_TOKEN") or None,
            mcp_url=source.get("MCP_URL") or "http://mcp-server:8100/mcp",
            mcp_token=source.get("MCP_SERVER_TOKEN") or source.get("API_AGENT_TOKEN") or None,
            mcp_timeout=float(source.get("MCP_TIMEOUT_SECONDS") or 20.0),
            poll_timeout=int(source.get("TELEGRAM_POLL_TIMEOUT") or 30),
        )

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token)

    @property
    def allowlists_configured(self) -> bool:
        return bool(self.telegram_allowed_users)
