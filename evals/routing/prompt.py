"""Load the versioned routing request both arms send.

The prompt is data in `prompts/0002-router-model-comparison.md`: a header block and one request block
with `{{message}}` as the only variable. Loading it from the file, rather than restating it in code,
means the reviewed text is what ran and a changed criterion is a visible version bump.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

BLOCK = re.compile(r"```yaml\n(.*?)```", re.DOTALL)
PLACEHOLDER = "{{message}}"
SURFACE_LABELS = {"database", "notes", "clarify", "refuse"}
TOOL_LABELS = {
    "get_standings",
    "get_fixtures",
    "get_match_result",
    "get_team_form",
    "get_head_to_head",
    "get_data_freshness",
    "not_applicable",
}


class PromptError(ValueError):
    """The versioned prompt is missing, malformed, or no longer matches the harness's contract."""


@dataclass(frozen=True)
class RouterPrompt:
    version: int
    models: str
    source: Path
    state_template: str
    questions: dict

    def render(self, message: str) -> str:
        if PLACEHOLDER not in self.state_template:
            raise PromptError(f"{self.source}: state template has no {PLACEHOLDER}")
        return self.state_template.replace(PLACEHOLDER, message)


def load_router_prompt(path: Path) -> RouterPrompt:
    blocks = BLOCK.findall(path.read_text(encoding="utf-8"))
    if len(blocks) != 2:
        raise PromptError(f"{path}: expected two yaml blocks (header, request), found {len(blocks)}")
    header = yaml.safe_load(blocks[0])
    body = yaml.safe_load(blocks[1])
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise PromptError(f"{path}: a yaml block is not a mapping")

    state = body.get("state")
    if not isinstance(state, str) or PLACEHOLDER not in state:
        raise PromptError(f"{path}: `state` must be a string containing {PLACEHOLDER}")
    questions = body.get("questions")
    if not isinstance(questions, dict) or set(questions) != {"surface", "tool"}:
        raise PromptError(f"{path}: questions must be exactly `surface` and `tool`")
    for name, labels in (("surface", SURFACE_LABELS), ("tool", TOOL_LABELS)):
        question = questions[name]
        if not isinstance(question, dict) or question.get("type") != "choice":
            raise PromptError(f"{path}: {name} is not a choice question")
        criteria = question.get("criteria")
        if not isinstance(criteria, dict) or set(criteria) != labels:
            raise PromptError(f"{path}: {name} criteria must be exactly {sorted(labels)}")

    version = header.get("version")
    models = header.get("model")
    if not isinstance(version, int) or not isinstance(models, str) or not models:
        raise PromptError(f"{path}: header needs an integer `version` and a `model`")

    return RouterPrompt(
        version=version,
        models=models,
        source=path,
        state_template=state,
        questions=questions,
    )
