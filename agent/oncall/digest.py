"""Render and write the daily data-quality digest.

The digest is deterministic from one snapshot: same rows, same report. It is a file because a file can
be diffed, and a diff is how an owner sees that yesterday's freshness or grounded rate changed. The
header records the window and the commit, so a digest is reproducible rather than a claim.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from agent.oncall.alerts import AlertState
from agent.oncall.queries import Snapshot


def render(snapshot: Snapshot, state: AlertState, *, generated_at: datetime, git_commit: str = "unknown") -> str:
    observation = snapshot.observation
    lines = [
        "# Hermes Football — daily data-quality digest",
        "",
        f"- generated: {generated_at.astimezone(UTC).isoformat()}",
        "- window: the 24 h ending at the generation time; freshness is measured to that moment",
        f"- commit: {git_commit}",
        f"- alert: **{state.state}** ({state.reason or 'none'})",
        "",
        "## Freshness",
        "",
        "| Competition | Status | Age (min) | Last success | Matches | Standings | Teams |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in snapshot.freshness.get("competitions") or []:
        rows = entry.get("rows") or {}
        lines.append(
            f"| {entry.get('code')} | {entry.get('status')} | {entry.get('age_minutes')} | "
            f"{entry.get('last_success_at') or 'never'} | {rows.get('matches', 0)} | "
            f"{rows.get('standings', 0)} | {rows.get('teams', 0)} |"
        )
    lines += [
        "",
        f"Overall: **{snapshot.freshness.get('overall_status')}**; "
        f"max age: {snapshot.freshness.get('max_age_minutes')} min.",
        "",
        "## Ingestion, last 24 h",
        "",
        f"- runs by status: {snapshot.runs_24h or 'none'}",
        "- newest successful run: "
        + (observation.last_success_at.isoformat() if observation.last_success_at else "never"),
        "- stuck `running` rows: "
        + (observation.oldest_running_at.isoformat() if observation.oldest_running_at else "none"),
        "",
        "## Agent turns, last 24 h",
        "",
        f"- total: {snapshot.turns_24h.get('total', 0)}; grounded: {snapshot.turns_24h.get('grounded', 0)} "
        f"({snapshot.turns_24h.get('grounded_rate')})",
        f"- by route: {snapshot.turns_24h.get('by_route') or 'none'}",
        f"- review status: {snapshot.turns_24h.get('reviewed') or 'none'}",
        "",
        "Message text is not read by this job: the digest is counts and statuses only.",
        "",
        "## Evaluation",
        "",
    ]
    if snapshot.eval_run:
        run = snapshot.eval_run
        lines += [
            f"- newest run: `{run['id']}` on `{run['set_name']}` ({run['source']}), "
            f"passed: {run['passed']}, macro-F1: {run['macro_f1']}",
            f"- age: {snapshot.eval_age_days} days (warn over 8)",
        ]
    else:
        lines.append("- no eval run is stored")
    lines += ["", "## Bounds", "", "Read-only role; no database writes; no model call; no upstream call.", ""]
    return "\n".join(lines)


def write(snapshot: Snapshot, state: AlertState, *, report_dir: Path, generated_at: datetime) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"digest-{generated_at.astimezone(UTC).date().isoformat()}.md"
    text = render(
        snapshot,
        state,
        generated_at=generated_at,
        git_commit=(os.environ.get("GIT_COMMIT") or "unknown")[:12],
    )
    path.write_text(text, encoding="utf-8")
    return path
