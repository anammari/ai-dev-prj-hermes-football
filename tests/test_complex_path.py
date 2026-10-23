"""The complex path: clef says complex, beam plans and composes, the verifier guards the draft."""

from __future__ import annotations

import json
from pathlib import Path

from agent.gate import apply
from agent.gateway.answer_composer import AnswerComposer
from agent.gateway.answer_verifier import AnswerVerifier
from agent.gateway.chat import ChatError
from agent.gateway.pipeline import Pipeline
from agent.gateway.planner import Planner
from agent.gateway.verify import verify_complex

PLANNER = Path(__file__).resolve().parents[1] / "prompts" / "0004-complex-planner.md"
COMPOSER = Path(__file__).resolve().parents[1] / "prompts" / "0005-complex-composer.md"
VERIFIER = Path(__file__).resolve().parents[1] / "prompts" / "0006-complex-verifier.md"
TOOLS = [
    {"name": "get_standings", "description": "League table."},
    {"name": "get_team_form", "description": "Recent results."},
    {"name": "get_fixtures", "description": "Upcoming matches."},
]
STANDINGS = {
    "competition": {"code": "PL", "name": "Premier League"},
    "data_as_of": "2026-10-22T02:01:00Z",
    "focus": {"position": 2, "team": "Arsenal FC", "played": 7, "points": 18, "goal_difference": 6},
    "rows": [],
}
FORM = {
    "team": {"name": "Arsenal FC"},
    "data_as_of": "2026-10-22T02:01:00Z",
    "summary": {"played": 5, "won": 4, "drawn": 0, "lost": 1, "points": 12, "clean_sheets": 2},
}
KNOWLEDGE = {
    "query": "serie a tiebreak",
    "data_as_of": None,
    "hits": [
        {
            "source_file": "tiebreakers/serie-a-level-points.md",
            "heading": "Serie A tiebreakers",
            "score": 0.8,
            "snippet": "Two clubs level on points for 1st place play a single match.",
        }
    ],
}


class FakeChat:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], *, temperature: float = 0.0) -> str:
        self.calls.append(messages)
        if not self.responses:
            raise ChatError("no response")
        return self.responses.pop(0)


class FakeRouter:
    def __init__(self, surface: str = "tool", tool: str = "get_standings") -> None:
        self.surface = surface
        self.tool = tool

    def route(self, message: str):
        return apply(
            surface_route=self.surface,
            tool=self.tool if self.surface == "tool" else None,
            surface_confidence=0.8,
            complexity="complex",
            safety="safe",
            safety_confidence=0.9,
            latency_ms=5,
        )


class FakeTools:
    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, dict]] = []

    def tools(self) -> list[dict]:
        return TOOLS

    def call(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return self.payloads[name]


class FakeTurns:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return "turn-1"


def _planner(chat: FakeChat) -> Planner:
    return Planner(chat, PLANNER)


def _composer(chat: FakeChat) -> AnswerComposer:
    return AnswerComposer(chat, COMPOSER)


def test_the_planner_returns_the_allowlisted_steps() -> None:
    chat = FakeChat([json.dumps({"steps": [{"tool": "get_standings"}, {"tool": "get_team_form"}]})])
    assert _planner(chat).plan("compare Arsenal", fallback_tool="get_standings", tools=TOOLS) == [
        "get_standings",
        "get_team_form",
    ]


def test_the_planner_drops_unknown_and_duplicate_tools() -> None:
    plan = {"steps": [{"tool": "get_standings"}, {"tool": "drop_tables"}, {"tool": "get_standings"}]}
    chat = FakeChat([json.dumps(plan)])
    assert _planner(chat).plan("x", fallback_tool="get_standings", tools=TOOLS) == ["get_standings"]


def test_the_planner_falls_back_on_invalid_json() -> None:
    chat = FakeChat(["not json"])
    assert _planner(chat).plan("x", fallback_tool="get_team_form", tools=TOOLS) == ["get_team_form"]


def test_the_planner_falls_back_when_the_model_fails() -> None:
    chat = FakeChat([])
    assert _planner(chat).plan("x", fallback_tool="get_fixtures", tools=TOOLS) == ["get_fixtures"]


def test_the_composer_receives_only_the_results_and_route() -> None:
    chat = FakeChat(["answer"])
    text = _composer(chat).compose("question", route="database", results={"get_standings": STANDINGS})
    assert text == "answer"
    sent = json.dumps(chat.calls[0])
    assert "2026-10-22T02:01:00Z" in sent
    assert "database" in sent


def test_the_model_verifier_accepts_a_supported_draft() -> None:
    chat = FakeChat([json.dumps({"supported": True, "unsupported": []})])
    verifier = AnswerVerifier(chat, VERIFIER)
    assert verifier.verify("question", route="database", results={"get_standings": STANDINGS}, draft="draft") is True


def test_the_model_verifier_rejects_an_unsupported_draft() -> None:
    chat = FakeChat([json.dumps({"supported": False, "unsupported": ["invented fact"]})])
    verifier = AnswerVerifier(chat, VERIFIER)
    assert verifier.verify("question", route="database", results={"get_standings": STANDINGS}, draft="draft") is False


def test_the_verifier_accepts_a_cited_tool_answer() -> None:
    text = "Arsenal are 2nd. As of 2026-10-22, source: football-data.org."
    assert verify_complex(text, route="tool", results={"get_standings": STANDINGS}) is True


def test_the_verifier_rejects_a_tool_answer_without_the_source() -> None:
    assert verify_complex("Arsenal are 2nd.", route="tool", results={"get_standings": STANDINGS}) is False


def test_the_verifier_accepts_a_cited_note_answer() -> None:
    text = "Two clubs play a single match. Source: tiebreakers/serie-a-level-points.md, Serie A tiebreakers."
    assert verify_complex(text, route="knowledge", results={"search_knowledge": KNOWLEDGE}) is True


def _pipeline(chat: FakeChat, route: str = "tool") -> tuple[Pipeline, FakeTools, FakeTurns]:
    tools = FakeTools({"get_standings": STANDINGS, "get_team_form": FORM, "search_knowledge": KNOWLEDGE})
    turns = FakeTurns()
    pipeline = Pipeline(
        FakeRouter(surface=route, tool="get_standings"),
        tools,
        turns,
        model="clef:cloud",
        planner=_planner(chat),
        composer=_composer(chat),
        verifier=AnswerVerifier(chat, VERIFIER),
        composer_model="beam:cloud",
    )
    return pipeline, tools, turns


def test_a_complex_tool_turn_plans_two_tools_and_composes() -> None:
    grounded = (
        "Arsenal are 2nd with 18 points. As of 2026-10-22, source: football-data.org. "
        "Their last five: 4W 0D 1L."
    )
    chat = FakeChat(
        [
            json.dumps({"steps": [{"tool": "get_standings"}, {"tool": "get_team_form"}]}),
            grounded,
            json.dumps({"supported": True, "unsupported": []}),
        ]
    )
    pipeline, tools, turns = _pipeline(chat)
    answer = pipeline.answer("compare Arsenal's position with their form")
    assert [name for name, _ in tools.calls] == ["get_standings", "get_team_form"]
    assert answer.text == grounded
    assert answer.complexity == "complex"
    assert "beam:cloud" in answer.model
    assert len(answer.tool_calls) == 2
    assert turns.calls[0]["route"] == "tool"
    assert turns.calls[0]["grounded"] is True


def test_a_failed_composer_falls_back_to_the_deterministic_answer() -> None:
    chat = FakeChat([json.dumps({"steps": [{"tool": "get_standings"}]})])
    # No second response: the composer call raises ChatError.
    pipeline, tools, _ = _pipeline(chat)
    answer = pipeline.answer("where are Arsenal?")
    assert "Arsenal FC are 2nd" in answer.text
    assert "source: football-data.org" in answer.text
    assert answer.grounded is True


def test_an_ungrounded_composer_draft_falls_back() -> None:
    chat = FakeChat(
        [json.dumps({"steps": [{"tool": "get_standings"}]}), "Arsenal are the best team in the world."]
    )
    pipeline, _, _ = _pipeline(chat)
    answer = pipeline.answer("where are Arsenal?")
    assert "source: football-data.org" in answer.text
    assert answer.text != "Arsenal are the best team in the world."


def test_a_composer_fact_the_verifier_rejects_falls_back() -> None:
    draft = "Arsenal are 2nd and won the World Cup. As of 2026-10-22, source: football-data.org."
    chat = FakeChat(
        [
            json.dumps({"steps": [{"tool": "get_standings"}]}),
            draft,
            json.dumps({"supported": False, "unsupported": ["won the World Cup"]}),
        ]
    )
    pipeline, _, _ = _pipeline(chat)
    answer = pipeline.answer("where are Arsenal?")
    assert "source: football-data.org" in answer.text
    assert "World Cup" not in answer.text


def test_a_complex_knowledge_turn_composes_with_the_note_citation() -> None:
    cited = (
        "Two clubs level on points for 1st play a single match. "
        "Source: tiebreakers/serie-a-level-points.md, Serie A tiebreakers."
    )
    chat = FakeChat([cited, json.dumps({"supported": True, "unsupported": []})])
    pipeline, tools, _ = _pipeline(chat, route="knowledge")
    answer = pipeline.answer("how is the Serie A title decided if two teams are level?")
    question = "how is the Serie A title decided if two teams are level?"
    assert tools.calls[0] == ("search_knowledge", {"query": question, "k": 8})
    assert answer.text == cited
    assert answer.route == "knowledge"
    assert answer.complexity == "complex"
