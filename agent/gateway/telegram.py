"""Minimal Telegram Bot API client: long polling in, plain text out.

No inbound port is opened (`_docs/product-sspec.md` §4). The token stays in the environment and is
never logged; messages are split at Telegram's 4,096-character limit. The client knows only
`getUpdates`, `sendMessage` and `getMe`, which is all the gateway needs.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

API = "https://api.telegram.org"
MAX_MESSAGE = 4000


class TelegramError(RuntimeError):
    pass


@dataclass(frozen=True)
class Incoming:
    update_id: int
    chat_id: int
    user_id: int
    text: str


class TelegramClient:
    def __init__(self, token: str, *, timeout: float = 40.0) -> None:
        if not token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is unset")
        self._token = token
        self._client = httpx.Client(base_url=API, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def _post(self, method: str, payload: dict) -> object:
        try:
            response = self._client.post(f"/bot{self._token}/{method}", json=payload)
        except httpx.HTTPError as error:
            raise TelegramError(f"telegram {method} failed: {error}") from error
        if response.status_code != 200:
            raise TelegramError(f"telegram {method}: HTTP {response.status_code}")
        body = response.json()
        if not body.get("ok"):
            raise TelegramError(f"telegram {method}: {body.get('description', 'not ok')}")
        return body.get("result")

    def me(self) -> dict:
        result = self._post("getMe", {})
        return result if isinstance(result, dict) else {}

    def get_updates(self, offset: int, timeout: int = 30) -> list[dict]:
        result = self._post(
            "getUpdates",
            {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]},
        )
        return result if isinstance(result, list) else []

    def send_message(self, chat_id: int, text: str) -> None:
        for start in range(0, max(1, len(text)), MAX_MESSAGE):
            chunk = text[start : start + MAX_MESSAGE]
            if chunk:
                self._post("sendMessage", {"chat_id": chat_id, "text": chunk})


def parse_update(update: object) -> Incoming | None:
    if not isinstance(update, dict):
        return None
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    if not isinstance(text, str) or not text.strip():
        return None
    if sender.get("is_bot"):
        return None
    try:
        return Incoming(
            update_id=int(update["update_id"]),
            chat_id=int(chat["id"]),
            user_id=int(sender["id"]),
            text=text.strip(),
        )
    except (KeyError, TypeError, ValueError):
        return None
