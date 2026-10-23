"""Load the text blocks from a versioned prompt file.

The routing prompt has its own loader (`agent.prompt`); the planner and composer prompts are plain
`text` fences with `{{placeholders}}`, so this small loader keeps them reviewable in `prompts/` without
a second prompt format.

`fill` substitutes into the original template in one pass. It never rescans the inserted values, so a
user message containing `{{route}}` is text, not a second substitution, and an unknown placeholder in
the template is an error before a model call.
"""

from __future__ import annotations

import re
from pathlib import Path

BLOCK = re.compile(r"```text\n(.*?)```", re.DOTALL)
PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")


class PromptFileError(ValueError):
    pass


def load_text_blocks(path: Path, expected: int) -> list[str]:
    blocks = [block.strip() for block in BLOCK.findall(path.read_text(encoding="utf-8"))]
    if len(blocks) != expected:
        raise PromptFileError(f"{path}: expected {expected} text blocks, found {len(blocks)}")
    return blocks


def fill(template: str, values: dict[str, str]) -> str:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            missing.add(key)
            return match.group(0)
        return values[key]

    result = PLACEHOLDER.sub(replace, template)
    if missing:
        raise PromptFileError(f"prompt has no value for: {', '.join(sorted(missing))}")
    return result
