"""The gateway process: health endpoint plus Telegram long polling in a background thread.

The bot is private by default: with no `TELEGRAM_ALLOWED_USERS` every message is refused, and with no
`TELEGRAM_BOT_TOKEN` the process still serves `/health` but polls nothing. That makes `make up` safe on
a machine where Telegram has not been configured yet, while the real bot is one token and one
allowlist away.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from agent.config import AgentSettings
from agent.gateway.factory import Runtime, build_runtime
from agent.gateway.telegram import Incoming, TelegramClient, TelegramError, parse_update
from agent.turn_log import TurnLogError, hash_chat_id

LOGGER = logging.getLogger("hermes.gateway")

WELCOME = (
    "I'm Hermes Football. I answer from stored football data and from a small set of rules notes.\n\n"
    "Try:\n"
    "• where are Arsenal in the table?\n"
    "• when do Liverpool play next?\n"
    "• how does the Championship playoff work?\n"
    "• what happens if two Serie A teams finish level on points?\n\n"
    "I always say how old the data is and where it came from. If I don't have it, I say so."
)
PRIVATE = "This bot is private."
UNKNOWN = "I don't know that command. Try /help."
LOG_FAILED = "I couldn't record that answer, so I didn't send it. Please try again."


class Gateway:
    def __init__(self, settings: AgentSettings, runtime: Runtime, telegram: TelegramClient | None) -> None:
        self.settings = settings
        self.runtime = runtime
        self.telegram = telegram
        self.stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.telegram is None or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._poll_forever, name="telegram-poller", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self.stop.set()
        if self.telegram is not None:
            self.telegram.close()
        self.runtime.close()

    def _poll_forever(self) -> None:
        assert self.telegram is not None
        offset = 0
        while not self.stop.is_set():
            try:
                updates = self.telegram.get_updates(offset, timeout=self.settings.poll_timeout)
            except TelegramError as error:
                LOGGER.warning("telegram poll failed: %s", error)
                time.sleep(3)
                continue
            except Exception:
                LOGGER.exception("unexpected telegram poll failure")
                time.sleep(5)
                continue
            for update in updates:
                try:
                    offset = max(offset, int(update.get("update_id", 0)) + 1)
                except (AttributeError, TypeError, ValueError):
                    continue
                incoming = parse_update(update)
                if incoming is not None:
                    self.handle(incoming)

    def handle(self, incoming: Incoming) -> None:
        assert self.telegram is not None
        if incoming.user_id not in self.settings.telegram_allowed_users:
            LOGGER.warning("rejected a message from a user outside the allowlist")
            self._send(incoming.chat_id, PRIVATE)
            return

        text = incoming.text
        if text.startswith("/"):
            command = text.split()[0].split("@")[0].lower()
            if command in ("/start", "/help"):
                self._send(incoming.chat_id, WELCOME)
            elif command == "/id":
                self._send(incoming.chat_id, f"Your Telegram user id is {incoming.user_id}.")
            elif command == "/status":
                if incoming.user_id not in self.settings.telegram_admin_users:
                    self._send(incoming.chat_id, "That command is for the owner.")
                else:
                    self._send(
                        incoming.chat_id,
                        f"Gateway up. Router model: {self.settings.router_model}. "
                        f"Allowlisted users: {len(self.settings.telegram_allowed_users)}. "
                        f"Admins: {len(self.settings.telegram_admin_users)}.",
                    )
            else:
                self._send(incoming.chat_id, UNKNOWN)
            return

        chat_hash = None
        if self.settings.chat_hash_salt:
            chat_hash = hash_chat_id(incoming.chat_id, self.settings.chat_hash_salt)
        try:
            answer = self.runtime.pipeline.answer(text, chat_id_hash=chat_hash)
        except TurnLogError:
            LOGGER.error("turn recording failed; the answer was withheld")
            self._send(incoming.chat_id, LOG_FAILED)
            return
        except Exception:
            LOGGER.exception("the pipeline failed before producing an answer")
            self._send(incoming.chat_id, "Something went wrong. Please try again.")
            return
        LOGGER.info("turn recorded: route=%s source=%s grounded=%s", answer.route, answer.route_source, answer.grounded)
        self._send(incoming.chat_id, answer.text)

    def _send(self, chat_id: int, text: str) -> None:
        assert self.telegram is not None
        try:
            self.telegram.send_message(chat_id, text)
        except TelegramError as error:
            LOGGER.warning("telegram send failed: %s", error)


def create_app(
    *,
    settings: AgentSettings | None = None,
    runtime: Runtime | None = None,
    telegram: TelegramClient | None = None,
) -> FastAPI:
    settings = settings or AgentSettings.from_env()
    runtime = runtime or build_runtime(settings)
    if telegram is None and settings.telegram_enabled:
        telegram = TelegramClient(settings.telegram_bot_token or "")
    gateway = Gateway(settings, runtime, telegram)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        gateway.start()
        try:
            yield
        finally:
            await asyncio.to_thread(gateway.shutdown)

    app = FastAPI(
        title="Hermes Football gateway",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.gateway = gateway

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "hermes-football-gateway",
            "telegram": "configured" if settings.telegram_enabled else "disabled",
            "allowlist": len(settings.telegram_allowed_users),
            "router_model": settings.router_model,
        }

    return app

