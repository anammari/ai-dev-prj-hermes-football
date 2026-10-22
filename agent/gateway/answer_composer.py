"""Compose a complex answer from the collected results with `beam:cloud`.

No retrieval or tool call happens here. The composer receives exactly what the executor collected and a
strict prompt: only those results, a timestamp or a note citation, no outside facts. The verifier decides
whether the draft is acceptable; otherwise the gateway falls back to the deterministic composer.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.gateway.chat import ChatClient
from agent.gateway.prompts import fill, load_text_blocks

DEFAULT_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "0005-complex-composer.md"


class AnswerComposer:
    def __init__(self, chat: ChatClient, prompt_path: Path = DEFAULT_PROMPT) -> None:
        self._chat = chat
        self._system, self._user = load_text_blocks(prompt_path, 2)

    def compose(self, message: str, *, route: str, results: dict) -> str:
        results_json = json.dumps(results, ensure_ascii=False, indent=2)
        return self._chat.chat(
            [
                {"role": "system", "content": self._system},
                {
                    "role": "user",
                    "content": fill(self._user, {"message": message, "route": route, "results": results_json}),
                },
            ]
        )
