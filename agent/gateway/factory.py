"""Build the gateway runtime from the environment and close it cleanly."""

from __future__ import annotations

from dataclasses import dataclass

from agent.config import AgentSettings
from agent.gateway.answer_composer import AnswerComposer
from agent.gateway.answer_verifier import AnswerVerifier
from agent.gateway.chat import ChatClient
from agent.gateway.mcp_client import MCPClient
from agent.gateway.pipeline import Pipeline
from agent.gateway.planner import Planner
from agent.router import Router, build_router
from agent.turn_log import TurnLog


@dataclass
class Runtime:
    settings: AgentSettings
    router: Router
    tools: MCPClient
    turns: TurnLog
    chat: ChatClient
    pipeline: Pipeline

    def close(self) -> None:
        self.chat.close()
        self.tools.close()
        self.turns.close()


def build_runtime(settings: AgentSettings) -> Runtime:
    router = build_router(
        base_url=settings.router_base_url,
        model=settings.router_model,
        prompt_path=settings.router_prompt,
        timeout=settings.router_timeout,
    )
    tools = MCPClient(settings.mcp_url, settings.mcp_token, timeout=settings.mcp_timeout)
    turns = TurnLog(settings.agent_turn_dsn)
    chat = ChatClient(settings.composer_base_url, settings.composer_model, timeout=settings.composer_timeout)
    planner = Planner(chat, settings.planner_prompt)
    composer = AnswerComposer(chat, settings.composer_prompt)
    verifier = AnswerVerifier(chat, settings.verifier_prompt)
    pipeline = Pipeline(
        router,
        tools,
        turns,
        model=settings.router_model,
        planner=planner,
        composer=composer,
        verifier=verifier,
        composer_model=settings.composer_model,
    )
    return Runtime(
        settings=settings,
        router=router,
        tools=tools,
        turns=turns,
        chat=chat,
        pipeline=pipeline,
    )
