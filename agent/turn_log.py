"""The gateway's write path: one audit row per answered turn, through an insert-only role.

Rule 10 requires every answer to record which road it took. Rule 4 requires the agent's data path to be
read-only. Both hold here: this module writes `agent_turns` and nothing else, using a role that has
INSERT and SELECT on that one table (migration `0003_agent_turn_writer`). It never reads a football
table, never issues DDL and never takes SQL from a model.

The chat id is hashed before it gets here. `hash_chat_id` is the helper that does it; the raw id is
never stored or logged (`AGENTS.md` rule 6).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from db.models import ROUTE_SOURCES, ROUTES, AgentTurn

Route = Literal["tool", "knowledge", "clarify", "refuse"]
RouteSource = Literal["model", "fallback"]


class TurnLogError(RuntimeError):
    """The writer is not configured, or was asked to record something the schema forbids."""


def hash_chat_id(chat_id: int | str, salt: str | None) -> str:
    """Salted HMAC-SHA256 of the Telegram chat id. The salt is required; there is no unsalted mode."""
    if not salt:
        raise TurnLogError("CHAT_HASH_SALT is unset: refusing to hash a chat id without a salt")
    digest = hmac.new(salt.encode("utf-8"), str(chat_id).encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


def create_writer_engine(dsn: str) -> Engine:
    # Bound values include the user message and the answer. SQLAlchemy renders them in driver errors
    # by default, and the gateway logs exceptions; hide them so a failed insert cannot leak a turn.
    kwargs: dict = {"future": True, "pool_pre_ping": True, "hide_parameters": True}
    if dsn.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(dsn, **kwargs)


class TurnLog:
    def __init__(self, dsn: str | None) -> None:
        if not dsn:
            raise TurnLogError(
                "AGENT_TURN_DSN is unset: the gateway will not answer a turn it cannot record "
                "(AGENTS.md rule 10)"
            )
        self._engine = create_writer_engine(dsn)

    def close(self) -> None:
        self._engine.dispose()

    def record(
        self,
        *,
        user_message: str,
        answer: str,
        route: str,
        route_source: str,
        route_confidence: float | None,
        model: str | None = None,
        latency_ms: int | None = None,
        chat_id_hash: str | None = None,
        grounded: bool = False,
        data_as_of: datetime | None = None,
        tool_calls: list | None = None,
    ) -> str:
        if route not in ROUTES:
            raise TurnLogError(f"route {route!r} is not one of {ROUTES}")
        if route_source not in ROUTE_SOURCES:
            raise TurnLogError(f"route_source {route_source!r} is not one of {ROUTE_SOURCES}")
        if route_confidence is not None and not 0.0 <= route_confidence <= 1.0:
            raise TurnLogError("route_confidence must be between 0 and 1")
        if not user_message.strip():
            raise TurnLogError("refusing to record an empty user message")

        turn_id = str(uuid.uuid4())
        with self._engine.begin() as connection:
            connection.execute(
                AgentTurn.__table__.insert().values(
                    id=turn_id,
                    chat_id_hash=chat_id_hash,
                    user_message=user_message,
                    tool_calls=tool_calls,
                    answer=answer,
                    grounded=grounded,
                    data_as_of=data_as_of,
                    model=model,
                    latency_ms=latency_ms,
                    route=route,
                    route_source=route_source,
                    route_confidence=route_confidence,
                )
            )
        return turn_id
