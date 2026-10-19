"""The model comparison's pieces, held down without a model or a stack.

The sample checks, the prompt loader, the arm plumbing and the precision/recall arithmetic are all
deterministic. They are what a reviewer can re-run with `make test`; the real comparison comes from
`make router-spike`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from db.settings import REPO_ROOT
from evals.routing import score
from evals.routing.arms import LABEL_TO_ROUTE, route_message
from evals.routing.ollama import Answer, OllamaError
from evals.routing.prompt import PromptError, load_router_prompt
from evals.routing.tools import TOOL_BY_NAME, TOOLS

SAMPLE = REPO_ROOT / "evals" / "routing" / "sample.yaml"
PROMPT = REPO_ROOT / "prompts" / "0002-router-model-comparison.md"


class FakeModel:
    """Stands in for `SystemOne`: records the payload and returns a scripted answer."""

    def __init__(self, label: str = "database", tool: str = "get_fixtures", confidence: float = 0.8) -> None:
        self.model = "fake-model"
        self.label = label
        self.tool = tool
        self.confidence = confidence
        self.calls: list[tuple[str, dict]] = []
        self.error: Exception | None = None

    def ask(self, state: str, questions: dict) -> dict[str, Answer]:
        self.calls.append((state, questions))
        if self.error is not None:
            raise self.error
        probability = self.confidence
        return {
            "surface": Answer(label=self.label, confidence=probability, probabilities={self.label: probability}),
            "tool": Answer(label=self.tool, confidence=probability, probabilities={self.tool: probability}),
        }


def _prompt():
    return load_router_prompt(PROMPT)


# ------------------------------------------------------------------------------------------------
# The sample and the prompt.
# ------------------------------------------------------------------------------------------------


def test_sample_satisfies_the_pre_registered_protocol() -> None:
    assert score.validate_sample(score.load_sample(SAMPLE)) == []


def test_sample_is_balanced_and_stratified() -> None:
    sample = score.load_sample(SAMPLE)
    answerable = [question for question in sample.questions if question.route in {"tool", "knowledge"}]
    assert sum(1 for question in answerable if question.route == "tool") == 35
    assert sum(1 for question in answerable if question.route == "knowledge") == 35
    assert len({question.class_name for question in sample.questions}) == 17
    assert sum(1 for question in sample.questions if question.split == "dev") == 34


def test_validation_catches_a_leaky_message(tmp_path: Path) -> None:
    body = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    body["questions"][0]["message"] = "from the database: where are arsenal?"
    path = tmp_path / "sample.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    problems = score.validate_sample(score.load_sample(path))
    assert any("expected surface" in problem for problem in problems), problems


def test_prompt_loads_renders_and_holds_both_questions() -> None:
    prompt = _prompt()
    assert prompt.version == 1
    assert "tev1:0.8b" in prompt.models and "clef:cloud" in prompt.models
    rendered = prompt.render("when do arsenal play chelsea?")
    assert rendered == "when do arsenal play chelsea?"
    assert set(prompt.questions) == {"surface", "tool"}
    assert set(prompt.questions["surface"]["criteria"]) == {"database", "notes", "clarify", "refuse"}
    assert "not_applicable" in prompt.questions["tool"]["criteria"]


def test_prompt_without_placeholder_is_refused(tmp_path: Path) -> None:
    broken = tmp_path / "prompt.md"
    broken.write_text(PROMPT.read_text(encoding="utf-8").replace("{{message}}", "the message"), encoding="utf-8")
    with pytest.raises(PromptError, match="state"):
        load_router_prompt(broken)


# ------------------------------------------------------------------------------------------------
# The tool catalogue and the contract.
# ------------------------------------------------------------------------------------------------


def test_every_tool_calls_an_operation_the_contract_serves() -> None:
    spec = yaml.safe_load((REPO_ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    for tool in TOOLS:
        assert tool.operation in spec["paths"], f"{tool.name} names an operation the contract does not serve"
        assert "get" in spec["paths"][tool.operation], f"{tool.operation} is not a GET"
        assert tool.description


def test_scorer_gap_is_explicit() -> None:
    assert "get_scorers" not in TOOL_BY_NAME


# ------------------------------------------------------------------------------------------------
# The arms.
# ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "route"),
    [("database", "tool"), ("notes", "knowledge"), ("clarify", "clarify"), ("refuse", "refuse")],
)
def test_surface_labels_map_to_routes(label: str, route: str) -> None:
    model = FakeModel(label=label, tool="not_applicable")
    choice = route_message(model, _prompt(), "a message")
    assert choice.route == route
    assert choice.tool is None


def test_tool_is_kept_only_for_the_tool_route() -> None:
    kept = route_message(FakeModel(label="database", tool="get_fixtures"), _prompt(), "a message")
    assert kept.tool == "get_fixtures"
    dropped = route_message(FakeModel(label="notes", tool="get_fixtures"), _prompt(), "a message")
    assert dropped.tool is None


def test_not_applicable_is_not_a_tool() -> None:
    choice = route_message(FakeModel(label="database", tool="not_applicable"), _prompt(), "a message")
    assert choice.route == "tool"
    assert choice.tool is None


def test_a_failed_call_is_recorded_not_hidden() -> None:
    model = FakeModel()
    model.error = OllamaError("server down")
    choice = route_message(model, _prompt(), "a message")
    assert choice.route is None
    assert choice.error is not None
    assert "server down" in choice.error


def test_an_unknown_label_is_an_error() -> None:
    choice = route_message(FakeModel(label="vibes"), _prompt(), "a message")
    assert choice.route is None
    assert "unknown surface label" in (choice.error or "")


def test_the_model_sees_only_the_message_and_the_shared_request() -> None:
    model = FakeModel()
    route_message(model, _prompt(), "when do arsenal play chelsea?")
    state, questions = model.calls[0]
    assert state == "when do arsenal play chelsea?"
    assert questions == _prompt().questions
    flattened = repr(questions)
    for forbidden in ("expected", "rationale", "holdout", "split"):
        assert forbidden not in flattened


def test_label_map_is_complete() -> None:
    assert set(LABEL_TO_ROUTE) == {"database", "notes", "clarify", "refuse"}


# ------------------------------------------------------------------------------------------------
# Precision / recall.
# ------------------------------------------------------------------------------------------------


def _record(
    *,
    expected_route: str,
    expected_tool: str | None,
    route: str | None,
    tool: str | None = None,
    latency_ms: float = 1.0,
    class_name: str = "standings",
    split: str = "dev",
    error: str | None = None,
) -> dict:
    return {
        "id": f"{class_name}-x",
        "class": class_name,
        "split": split,
        "message": "m",
        "expected_route": expected_route,
        "expected_tool": expected_tool,
        "route": route,
        "tool": tool,
        "confidence": 0.5 if route else None,
        "label": None,
        "error": error,
        "latency_ms": latency_ms,
    }


def test_precision_and_recall_are_per_route() -> None:
    rows = [
        _record(expected_route="tool", expected_tool="get_standings", route="tool", tool="get_standings"),
        _record(expected_route="tool", expected_tool="get_standings", route="knowledge"),
        _record(expected_route="knowledge", expected_tool=None, route="knowledge"),
        _record(expected_route="knowledge", expected_tool=None, route="tool", tool="get_standings"),
    ]
    result = score.score_model(rows)
    tool = result["per_route"]["tool"]
    knowledge = result["per_route"]["knowledge"]
    assert (tool["tp"], tool["fp"], tool["fn"]) == (1, 1, 1)
    assert tool["precision"] == pytest.approx(0.5)
    assert tool["recall"] == pytest.approx(0.5)
    assert knowledge["precision"] == pytest.approx(0.5)
    assert knowledge["recall"] == pytest.approx(0.5)
    assert result["accuracy"] == pytest.approx(0.5)
    assert result["macro_f1"] == pytest.approx(0.5 / 4 + 0.5 / 4, abs=1e-6)


def test_tool_precision_and_recall_use_only_labelled_tools() -> None:
    rows = [
        _record(expected_route="tool", expected_tool="get_standings", route="tool", tool="get_standings"),
        _record(expected_route="tool", expected_tool="get_standings", route="tool", tool="get_fixtures"),
        _record(expected_route="tool", expected_tool=None, route="tool", tool="get_fixtures"),
    ]
    result = score.score_model(rows)["tool"]
    assert (result["tp"], result["fp"], result["fn"]) == (1, 1, 1)
    assert result["precision"] == pytest.approx(0.5)
    assert result["recall"] == pytest.approx(0.5)


def test_a_failed_call_counts_as_a_miss() -> None:
    rows = [_record(expected_route="knowledge", expected_tool=None, route=None, error="timeout")]
    result = score.score_model(rows)
    assert result["errors"] == 1
    assert result["accuracy"] == 0
    assert result["per_route"]["knowledge"]["fn"] == 1


def test_percentile_uses_the_nearest_rank() -> None:
    assert score.percentile([1, 2, 3, 4, 5], 0.95) == 5
    assert score.percentile(list(range(1, 101)), 0.95) == 95
    assert score.percentile([], 0.95) == 0.0


def test_markdown_report_has_the_two_model_tables() -> None:
    rows = [
        _record(expected_route="tool", expected_tool="get_standings", route="tool", tool="get_standings"),
        _record(
            expected_route="knowledge",
            expected_tool=None,
            route="knowledge",
            split="holdout",
        ),
    ]
    scores = {
        key: {split: score.score_model(rows, split) for split in ("dev", "holdout", "all")}
        for key in ("model1", "model2")
    }
    meta = {"run_id": "test", "sample_sha256": "0" * 64, "prompt_version": 1}
    text = score.render_markdown(meta, {"model1": rows, "model2": rows}, scores)
    assert "Model-1 tev1:0.8b" in text
    assert "Model-2 clef:cloud" in text
    assert "Per-route precision / recall" in text
