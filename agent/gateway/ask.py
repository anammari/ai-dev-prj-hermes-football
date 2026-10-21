"""Ask the gateway one question from the shell, without Telegram.

This runs the same pipeline the bot runs: router, gate, MCP tool, composer, turn row. It is the quick
way to prove a database question and a notes question end to end on a machine with no bot token.
"""

from __future__ import annotations

import argparse
import json
import sys

from agent.config import AgentSettings
from agent.gateway.factory import build_runtime
from agent.turn_log import hash_chat_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--message", required=True)
    parser.add_argument("--chat-id", default=None, help="optional Telegram chat id; stored only as a salted hash")
    args = parser.parse_args(argv)

    settings = AgentSettings.from_env()
    runtime = build_runtime(settings)
    chat_hash = None
    if args.chat_id and settings.chat_hash_salt:
        chat_hash = hash_chat_id(args.chat_id, settings.chat_hash_salt)
    try:
        answer = runtime.pipeline.answer(args.message, chat_id_hash=chat_hash)
    finally:
        runtime.close()

    print(answer.text)
    print(
        json.dumps(
            {
                "route": answer.route,
                "route_source": answer.route_source,
                "route_confidence": answer.route_confidence,
                "route_reason": answer.route_reason,
                "grounded": answer.grounded,
                "latency_ms": answer.latency_ms,
                "turn_id": answer.turn_id,
                "tool_calls": answer.tool_calls,
            },
            indent=2,
        )
    )
    return 0 if answer.turn_id else 1


if __name__ == "__main__":
    sys.exit(main())
