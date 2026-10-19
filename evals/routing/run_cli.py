"""Run the two-model routing spike and write its evidence.

`make router-spike` is the only intended caller. The run:

1. loads the frozen sample and refuses to start if it violates the protocol;
2. loads the versioned request both models receive, and probes both servers;
3. asks both models every question in a fixed shuffled order, recording failures rather than hiding them;
4. writes `results/<run-id>.json` (every choice and timing) and `.md` (precision/recall tables).

Model-1 runs in the profile-gated local Ollama. Model-2 is `clef:cloud`, which sends the message to
Ollama's cloud; that is recorded in the artifact and is a blocker for adopting it in the product, whose
inference is local-only (`_docs/product-spec.md` §4). The messages here are synthetic eval questions, not
user conversations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

from evals.routing import score
from evals.routing.arms import as_record, route_message
from evals.routing.ollama import OllamaError, OllamaProbe, SystemOne
from evals.routing.prompt import load_router_prompt

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE = REPO_ROOT / "evals" / "routing" / "sample.yaml"
DEFAULT_PROMPT = REPO_ROOT / "prompts" / "0002-router-model-comparison.md"
DEFAULT_OUT = REPO_ROOT / "evals" / "routing" / "results"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_cloud(model: str) -> bool:
    return model.endswith(":cloud") or model.endswith("-cloud")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model1", default=os.environ.get("ROUTER_MODEL1", "tev1:0.8b"))
    parser.add_argument("--model2", default=os.environ.get("ROUTER_MODEL2", "clef:cloud"))
    parser.add_argument("--base-url1", default=os.environ.get("ROUTER_URL1", "http://ollama-spike:11434"))
    parser.add_argument("--base-url2", default=os.environ.get("ROUTER_URL2", "http://host.docker.internal:11434"))
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    sample = score.load_sample(args.sample)
    problems = score.validate_sample(sample)
    if problems:
        print("sample failed its own protocol:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    prompt = load_router_prompt(args.prompt)
    run_id = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")

    with (
        SystemOne(args.base_url1, args.model1, args.timeout) as model1,
        SystemOne(args.base_url2, args.model2, args.timeout) as model2,
        OllamaProbe(args.base_url1) as probe1,
        OllamaProbe(args.base_url2) as probe2,
    ):
        servers = {}
        for label, probe, model_name in (("model1", probe1, args.model1), ("model2", probe2, args.model2)):
            try:
                models = probe.models()
                version = probe.version()
            except OllamaError as error:
                print(f"{label}: server unreachable: {error}", file=sys.stderr)
                return 2
            if model_name not in models and not _is_cloud(model_name):
                print(f"{label}: server has no model {model_name!r}", file=sys.stderr)
                return 2
            info = models.get(model_name)
            servers[label] = {
                "model": model_name,
                "base_url": args.base_url1 if label == "model1" else args.base_url2,
                "ollama_version": version,
                "digest": info.digest if info else None,
                "size": info.size if info else None,
                "cloud": _is_cloud(model_name),
            }

        questions = [
            {
                "id": question.id,
                "class": question.class_name,
                "split": question.split,
                "message": question.message,
                "expected_route": question.route,
                "expected_tool": question.tool,
            }
            for question in sample.questions
        ]
        random.Random(sample.seed).shuffle(questions)

        records_by_model: dict[str, list[dict]] = {"model1": [], "model2": []}
        for index, question in enumerate(questions, start=1):
            choice1 = route_message(model1, prompt, question["message"])
            choice2 = route_message(model2, prompt, question["message"])
            question["model1"] = as_record(choice1)
            question["model2"] = as_record(choice2)
            for key, choice in (("model1", choice1), ("model2", choice2)):
                records_by_model[key].append(
                    {
                        "id": question["id"],
                        "class": question["class"],
                        "split": question["split"],
                        "message": question["message"],
                        "expected_route": question["expected_route"],
                        "expected_tool": question["expected_tool"],
                        **as_record(choice),
                    }
                )
            print(f"[{index:02d}/{len(questions)}] {question['id']}", file=sys.stderr)

    scores = {
        key: {split: score.score_model(rows, split) for split in ("dev", "holdout", "all")}
        for key, rows in records_by_model.items()
    }

    meta = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": os.environ.get("GIT_COMMIT", "unknown"),
        "sample_path": str(args.sample.relative_to(REPO_ROOT)),
        "sample_sha256": _sha256(args.sample),
        "prompt_path": str(args.prompt.relative_to(REPO_ROOT)),
        "prompt_sha256": _sha256(args.prompt),
        "prompt_version": prompt.version,
        "seed": sample.seed,
        "servers": servers,
        "egress": {
            "model1": "local: spike-only Ollama container, no cloud",
            "model2": "cloud: clef:cloud sends each message to Ollama's cloud",
        },
        "target_macro_f1": score.TARGET_MACRO_F1,
        "decision_rule": "evals/routing/README.md section 5",
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / f"{run_id}.json"
    md_path = args.out_dir / f"{run_id}.md"
    json_path.write_text(
        json.dumps({"meta": meta, "questions": questions, "records": records_by_model, "scores": scores}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    md_path.write_text(score.render_markdown(meta, records_by_model, scores), encoding="utf-8")

    for key in ("model1", "model2"):
        hold = scores[key]["holdout"]
        print(
            f"{key} ({servers[key]['model']}) holdout acc {hold['accuracy']:.0%}, "
            f"macro P {hold['macro_precision']:.2f}, R {hold['macro_recall']:.2f}, F1 {hold['macro_f1']:.2f}, "
            f"errors {hold['errors']}"
        )
    print(f"wrote {json_path.relative_to(REPO_ROOT)} and {md_path.relative_to(REPO_ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(_parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
