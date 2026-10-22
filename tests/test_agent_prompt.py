"""The production prompt is a contract: exactly three choice questions, exactly these labels."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.prompt import PromptError, load_router_prompt

PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "0003-agent-router.md"


def test_the_production_prompt_loads_and_sends_the_message_unchanged() -> None:
    prompt = load_router_prompt(PROMPT)
    message = "where are Arsenal in the table?"
    assert prompt.version == 2
    assert prompt.render(message) == message
    payload = prompt.payload(message, "clef:cloud")
    assert payload["model"] == "clef:cloud"
    assert payload["state"] == message
    assert set(payload["questions"]) == {"surface", "tool", "complexity", "safety"}


def test_each_question_has_exactly_its_reviewed_labels() -> None:
    prompt = load_router_prompt(PROMPT)
    assert set(prompt.questions["surface"]["criteria"]) == {"database", "notes", "clarify", "refuse"}
    assert set(prompt.questions["tool"]["criteria"]) == {
        "get_standings",
        "get_fixtures",
        "get_match_result",
        "get_team_form",
        "get_head_to_head",
        "get_data_freshness",
        "not_applicable",
    }
    assert set(prompt.questions["safety"]["criteria"]) == {"safe", "instruction_override", "fabricated_fact"}
    assert set(prompt.questions["complexity"]["criteria"]) == {"simple", "complex"}


def _mutated(tmp_path: Path, old: str, new: str) -> Path:
    target = tmp_path / "prompt.md"
    target.write_text(PROMPT.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    return target


def test_extra_text_around_the_placeholder_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="state"):
        load_router_prompt(_mutated(tmp_path, 'state: "{{message}}"', 'state: "User: {{message}}"'))


def test_an_extra_question_is_rejected(tmp_path: Path) -> None:
    extra = "  extra:\n    type: choice\n    criteria:\n      a: b\n"
    with pytest.raises(PromptError, match="questions"):
        load_router_prompt(_mutated(tmp_path, "questions:\n  surface:", "questions:\n" + extra + "  surface:"))


def test_a_missing_safety_label_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="safety"):
        load_router_prompt(_mutated(tmp_path, "      fabricated_fact:", "      made_up:"))


def test_one_yaml_block_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "prompt.md"
    target.write_text(PROMPT.read_text(encoding="utf-8").split("```yaml", 2)[0], encoding="utf-8")
    with pytest.raises(PromptError, match="yaml blocks"):
        load_router_prompt(target)
