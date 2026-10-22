"""Plan the tool calls for a complex database question.

The planner sees the user message and the MCP tool catalogue, never tool output. It returns tool names
only; the gateway calls each with the user message, so the tool's own resolver owns arguments. An
invalid plan falls back to the tool the router already chose.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agent.gateway.chat import ChatClient
from agent.gateway.prompts import fill, load_text_blocks

DEFAULT_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "0004-complex-planner.md"
MAX_STEPS = 4
_JSON = re.compile(r"\{.*\}", re.DOTALL)


class Planner:
    def __init__(self, chat: ChatClient, prompt_path: Path = DEFAULT_PROMPT) -> None:
        self._chat = chat
        self._template = load_text_blocks(prompt_path, 1)[0]

    def plan(self, message: str, *, fallback_tool: str, tools: list[dict]) -> list[str]:
        available = [str(tool.get("name")) for tool in tools if tool.get("name")]
        if not available:
            return [fallback_tool] if fallback_tool in available or fallback_tool else []
        catalogue = "\n".join(f"- {tool['name']}: {tool.get('description', '')}" for tool in tools if tool.get("name"))
        prompt = fill(self._template, {"tools": catalogue, "message": message})
        try:
            raw = self._chat.chat([{"role": "user", "content": prompt}])
            steps = self._parse(raw)
        except Exception:
            return [fallback_tool]
        chosen: list[str] = []
        for name in steps:
            if name in available and name not in chosen:
                chosen.append(name)
            if len(chosen) == MAX_STEPS:
                break
        return chosen or [fallback_tool]

    @staticmethod
    def _parse(raw: str) -> list[str]:
        match = _JSON.search(raw)
        if match is None:
            return []
        body = json.loads(match.group(0))
        steps = body.get("steps") if isinstance(body, dict) else None
        if not isinstance(steps, list):
            return []
        names: list[str] = []
        for step in steps:
            if isinstance(step, str):
                names.append(step)
            elif isinstance(step, dict) and isinstance(step.get("tool"), str):
                names.append(step["tool"])
        return names
