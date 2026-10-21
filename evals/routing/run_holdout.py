"""Run the frozen M4 holdout once and write its evidence.

Protocol: the 60 questions were authored by an independent reviewer and audited by a second before this
file existed; both records are in `results/`. This runner refuses to start if the holdout no longer
matches its protocol, sends each question once, and records a failed call as a miss rather than
retrying it. Raw (pre-gate) and gated scores are both reported so the gate's marginal effect is visible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from agent.router import build_router
from evals.routing import holdout as protocol
from evals.routing.ollama import OllamaError, OllamaProbe

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOLDOUT = REPO_ROOT / "evals" / "routing" / "holdout-2026-10-22.yaml"
DEFAULT_PROMPT = REPO_ROOT / "prompts" / "0003-agent-router.md"
DEFAULT_OUT = REPO_ROOT / "evals" / "routing" / "results"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("ROUTER_BASE_URL", "http://localhost:11434"))
    parser.add_argument("--model", default=os.environ.get("ROUTER_MODEL", "clef:cloud"))
    parser.add_argument("--holdout", type=Path, default=DEFAULT_HOLDOUT)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    sample = protocol.load_holdout(args.holdout)
    problems = protocol.validate_holdout(sample)
    if problems:
        print("holdout failed its own protocol:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    prompt_sha = _sha256(args.prompt)
    holdout_sha = _sha256(args.holdout)
    router = build_router(
        base_url=args.base_url,
        model=args.model,
        prompt_path=args.prompt,
        timeout=args.timeout,
    )
    run_id = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")

    try:
        with OllamaProbe(args.base_url) as probe:
            ollama_version = probe.version()
            models = probe.models()
    except OllamaError as error:
        print(f"decision server unreachable: {error}", file=sys.stderr)
        return 2
    info = models.get(args.model)

    questions = list(sample.questions)
    random.Random(sample.seed).shuffle(questions)

    records: list[dict] = []
    for question in questions:
        decision = router.route(question.message)
        records.append(
            {
                "id": question.id,
                "class": question.class_name,
                "message": question.message,
                "expected_route": question.route,
                "expected_tool": question.tool,
                "expected_reason": question.expected_reason,
                "raw_route": decision.surface_route,
                "raw_tool": decision.surface_tool,
                "route": decision.route,
                "tool": decision.tool,
                "route_source": decision.source,
                "route_confidence": decision.confidence,
                "reason": decision.reason,
                "safety": decision.safety,
                "latency_ms": round(decision.latency_ms, 3),
                "error": decision.error,
            }
        )

    raw = protocol.score(records, route_key="raw_route", tool_key="raw_tool")
    gated = protocol.score(records, route_key="route", tool_key="tool")

    meta = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "holdout_path": str(args.holdout.relative_to(REPO_ROOT)),
        "holdout_sha256": holdout_sha,
        "holdout_version": sample.version,
        "prompt_path": str(args.prompt.relative_to(REPO_ROOT)),
        "prompt_sha256": prompt_sha,
        "prompt_version": router.prompt_version,
        "model": args.model,
        "base_url": args.base_url,
        "ollama_version": ollama_version,
        "model_digest": info.digest if info else None,
        "model_size": info.size if info else None,
        "target_macro_f1": protocol.TARGET_MACRO_F1,
        "protocol": "evals/routing/README.md sections 4-5; decision 0003; decision 0006",
        "egress": (
            "cloud: clef:cloud sends each message to Ollama's cloud. The request body is the model, "
            "the user message and the fixed label sets only. No note text, tool output or chat id is sent."
        ),
        "decision": "target met" if gated["macro_f1"] >= protocol.TARGET_MACRO_F1 else "target not met; gap recorded",
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / f"{run_id}.json"
    md_path = args.out_dir / f"{run_id}.md"
    json_path.write_text(
        json.dumps({"meta": meta, "raw": raw, "gated": gated, "records": records}, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(protocol.render_markdown(meta, records, raw, gated), encoding="utf-8")

    print(f"run {run_id}")
    print(f"  holdout sha {holdout_sha[:12]} · prompt v{router.prompt_version} · model {args.model}")
    print(f"  raw   macro-F1 {raw['macro_f1']:.3f} · accuracy {raw['accuracy']:.3f}")
    print(f"  gated macro-F1 {gated['macro_f1']:.3f} · accuracy {gated['accuracy']:.3f} "
          f"· target {protocol.TARGET_MACRO_F1:.2f}")
    print(f"  gates {gated['gates']}")
    print(f"  false refusals {len(gated['false_refusals'])} · db->notes {len(gated['database_to_notes'])}")
    print(f"  wrote {json_path.relative_to(REPO_ROOT)} and {md_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(_parse_args(None)))
