"""Build the gateway runtime from the environment and close it cleanly."""

from __future__ import annotations

from dataclasses import dataclass

from agent.config import AgentSettings
from agent.gateway.mcp_client import MCPClient
from agent.gateway.pipeline import Pipeline
from agent.router import Router, build_router
from agent.turn_log import TurnLog


@dataclass
class Runtime:
    settings: AgentSettings
    router: Router
    tools: MCPClient
    turns: TurnLog
    pipeline: Pipeline

    def close(self) -> None:
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
    pipeline = Pipeline(router, tools, turns, model=settings.router_model)
    return Runtime(settings=settings, router=router, tools=tools, turns=turns, pipeline=pipeline)
