"""Ask the router one message, without Telegram or the database.

`python -m agent route --message "where are Arsenal in the table?"` prints the recorded decision:
route, source, confidence and the gate reason. It sends the message to `clef:cloud` and nothing else,
which makes it the quickest way to see the egress for yourself.
"""

from __future__ import annotations

import argparse
import json
import sys

from agent.config import AgentSettings
from agent.router import build_router


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    route = sub.add_parser("route", help="route one message")
    route.add_argument("--message", required=True)
    route.add_argument("--base-url", default=None)
    route.add_argument("--model", default=None)
    args = parser.parse_args(argv)

    settings = AgentSettings.from_env()
    router = build_router(
        base_url=args.base_url or settings.router_base_url,
        model=args.model or settings.router_model,
        prompt_path=settings.router_prompt,
        timeout=settings.router_timeout,
    )
    decision = router.route(args.message)
    print(json.dumps(decision.as_record(), indent=2, sort_keys=True))
    return 0 if decision.source == "model" else 2


if __name__ == "__main__":
    sys.exit(main())
