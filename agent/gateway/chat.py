"""A tiny Ollama chat client for the complex path (`beam:cloud`).

One POST to `/api/chat`, no streaming, thinking off by default. The client is used only by the planner
and composer, never by the simple path. A failure is an exception the gateway turns into the
deterministic fallback, so a cloud outage degrades the answer rather than dropping it.
"""

from __future__ import annotations

import httpx


class ChatError(RuntimeError):
    """The chat model is unreachable or answered without content."""


class ChatClient:
    def __init__(self, base_url: str, model: str, timeout: float = 90.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def chat(self, messages: list[dict], *, temperature: float = 0.0) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": temperature},
        }
        try:
            response = self._client.post("/api/chat", json=payload)
        except httpx.HTTPError as error:
            raise ChatError(f"{self.model}: request failed: {error}") from error
        if response.status_code != 200:
            raise ChatError(f"{self.model}: HTTP {response.status_code}: {response.text[:200]}")
        try:
            body = response.json()
        except ValueError as error:
            raise ChatError(f"{self.model}: response was not JSON") from error
        message = body.get("message") if isinstance(body, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ChatError(f"{self.model}: empty response")
        return content.strip()
