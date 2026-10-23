"""A focused second model call that checks a complex draft against the results.

The composer can produce a fluent sentence with a real timestamp and still add a fact the payload does
not contain. The deterministic check in `verify.py` catches a missing citation; this verifier asks the
model, with the same question and results, whether every factual claim is supported. It does not
rewrite the answer. A false or unparseable verdict is a fallback, not a rejection of the user.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agent.gateway.chat import ChatClient
from agent.gateway.prompts import fill, load_text_blocks

DEFAULT_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "0006-complex-verifier.md"
_JSON = re.compile(r"\{.*\}", re.DOTALL)


class AnswerVerifier:
    def __init__(self, chat: ChatClient, prompt_path: Path = DEFAULT_PROMPT) -> None:
        self._chat = chat
        self._system, self._user = load_text_blocks(prompt_path, 2)

    def verify(self, message: str, *, route: str, results: dict, draft: str) -> bool:
        payload = fill(
            self._user,
            {
                "message": message,
                "route": route,
                "results": json.dumps(results, ensure_ascii=False, indent=2),
                "draft": draft,
            },
        )
        try:
            raw = self._chat.chat(
                [{"role": "system", "content": self._system}, {"role": "user", "content": payload}]
            )
        except Exception:
            return False
        match = _JSON.search(raw)
        if match is None:
            return False
        try:
            body = json.loads(match.group(0))
        except ValueError:
            return False
        return isinstance(body, dict) and body.get("supported") is True
