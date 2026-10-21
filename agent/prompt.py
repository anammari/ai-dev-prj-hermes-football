"""Load and validate the versioned production routing request (`prompts/0003-agent-router.md`).

The request is data, not prose: a header block and one request block whose only variable is
`{{message}}`. Loading it from the file means the reviewed text is exactly what runs, and a changed
criterion is a visible version bump. The validator is deliberately strict: a fourth question, a
missing label, or extra text around the placeholder is a prompt change and must fail here rather than
silently widen what the user's message is sent with.
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
SAFETY_LABELS = {"safe", "instruction_override", "fabricated_fact"}
QUESTIONS = ("surface", "tool", "safety")
LABELS = {"surface": SURFACE_LABELS, "tool": TOOL_LABELS, "safety": SAFETY_LABELS}


class PromptError(ValueError):
    """The versioned request is missing, malformed, or no longer matches the router's contract."""


@dataclass(frozen=True)
class RouterPrompt:
    version: int
    model: str
    source: Path
    state_template: str
    questions: dict

    def render(self, message: str) -> str:
        if self.state_template != PLACEHOLDER:
            raise PromptError(f"{self.source}: `state` must be exactly {PLACEHOLDER!r}")
        return message

    def payload(self, message: str, model: str) -> dict:
        """The exact body sent to the decision endpoint: the model, the message, the label sets."""
        return {"model": model, "state": self.render(message), "questions": self.questions}


def load_router_prompt(path: Path) -> RouterPrompt:
    blocks = BLOCK.findall(path.read_text(encoding="utf-8"))
    if len(blocks) != 2:
        raise PromptError(f"{path}: expected two yaml blocks (header, request), found {len(blocks)}")
    header = yaml.safe_load(blocks[0])
    body = yaml.safe_load(blocks[1])
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise PromptError(f"{path}: a yaml block is not a mapping")

    state = body.get("state")
    if state != PLACEHOLDER:
        raise PromptError(f"{path}: `state` must be exactly {PLACEHOLDER!r}, found {state!r}")

    questions = body.get("questions")
    if not isinstance(questions, dict) or set(questions) != set(QUESTIONS):
        raise PromptError(f"{path}: questions must be exactly {sorted(QUESTIONS)}")
    for name in QUESTIONS:
        question = questions[name]
        if not isinstance(question, dict) or question.get("type") != "choice":
            raise PromptError(f"{path}: {name} is not a choice question")
        criteria = question.get("criteria")
        if not isinstance(criteria, dict) or set(criteria) != LABELS[name]:
            raise PromptError(f"{path}: {name} criteria must be exactly {sorted(LABELS[name])}")

    version = header.get("version")
    model = header.get("model")
    if not isinstance(version, int) or not isinstance(model, str) or not model:
        raise PromptError(f"{path}: header needs an integer `version` and a `model`")

    return RouterPrompt(
        version=version,
        model=model,
        source=path,
        state_template=state,
        questions=questions,
    )
