"""Every capability the project ships is declared, and the declaration is checked.

`AGENTS.md` rules 7 and 8 say a new tool is a new row in `security/capability-table.md` and an
undocumented capability is not shippable. A reviewer cannot hold that by memory, so this test reads
the table and compares it with the things that actually exist: the Compose services, the MCP tool
registry, the token names and the scheduled/manual jobs.

It is deliberately a name check, not a prose check. The table explains the bound; this proves the row
exists so a human reads it.
"""

from __future__ import annotations

import yaml

from db.settings import REPO_ROOT
from mcp_server.tools import TOOLS

TABLE = REPO_ROOT / "security" / "capability-table.md"
COMPOSE = REPO_ROOT / "docker-compose.yml"


def _table() -> str:
    return TABLE.read_text(encoding="utf-8")


def _services() -> list[str]:
    document = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return sorted((document.get("services") or {}).keys())


def test_every_compose_service_has_a_row() -> None:
    text = _table()
    missing = [name for name in _services() if f"`{name}`" not in text]
    assert not missing, f"services with no capability-table row: {missing}"


def test_every_mcp_tool_has_a_row() -> None:
    text = _table()
    missing = [name for name in TOOLS if f"`{name}`" not in text]
    assert not missing, f"MCP tools with no capability-table row: {missing}"


def test_every_token_is_named() -> None:
    text = _table()
    missing = [
        token
        for token in (
            "API_AGENT_TOKEN",
            "API_ADMIN_TOKEN",
            "MCP_SERVER_TOKEN",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_REVIEW_BOT_TOKEN",
            "TELEGRAM_ALERT_BOT_TOKEN",
            "CHAT_HASH_SALT",
            "AGENT_ADMIN_DB_PASSWORD",
        )
        if token not in text
    ]
    assert not missing, f"tokens with no capability-table row: {missing}"


def test_every_scheduled_or_manual_job_is_named() -> None:
    text = _table()
    missing = [
        job
        for job in (
            "daily ingestion",
            "re-index changed notes",
            "make ingest",
            "make score-delay",
            "make eval",
            "make eval-backfill",
            "on-call digest",
            "alert evaluator",
            "CI",
            "nightly",
            "make security-scan",
        )
        if job not in text
    ]
    assert not missing, f"jobs with no capability-table row: {missing}"


def test_the_table_names_the_rule_it_implements() -> None:
    text = _table()
    assert "AGENTS.md" in text
    assert "tests/test_capability_table.py" in text, "the table must say how it is enforced"


def test_the_table_is_not_empty_and_has_the_five_columns() -> None:
    lines = [line for line in _table().splitlines() if line.startswith("|")]
    assert len(lines) >= 40, "the capability table lost rows"
    assert any("May not" in line for line in lines)
