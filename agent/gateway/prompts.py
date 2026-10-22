"""Load the text blocks from a versioned prompt file.

The routing prompt has its own loader (`agent.prompt`); the planner and composer prompts are plain
`text` fences with `{{placeholders}}`, so this small loader keeps them reviewable in `prompts/` without
a second prompt format.
"""

from __future__ import annotations

import re
from pathlib import Path

BLOCK = re.compile(r"```text\n(.*?)```", re.DOTALL)


class PromptFileError(ValueError):
    pass


def load_text_blocks(path: Path, expected: int) -> list[str]:
    blocks = [block.strip() for block in BLOCK.findall(path.read_text(encoding="utf-8"))]
    if len(blocks) != expected:
        raise PromptFileError(f"{path}: expected {expected} text blocks, found {len(blocks)}")
    return blocks


def fill(template: str, values: dict[str, str]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace("{{" + key + "}}", value)
    if "{{" in result:
        raise PromptFileError(f"unfilled placeholder in prompt: {result[:120]}")
    return result
