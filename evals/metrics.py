"""The arithmetic every eval report shares.

Four numbers decide whether a model or a run is good: per-class precision/recall/F1, their macro
average, and a percentile for latency. They were written twice - once for the archived two-model
comparison (`evals/routing/score.py`) and once for the M4 holdout (`evals/routing/holdout.py`) - and
M5 would have made it three. Extracting them here means the routing scoreboard and the M4 artifacts
are computed by the same code, which is the only way their numbers can be compared at all.

The functions are pure and total: an empty class scores 0.0 rather than raising, because a route the
model never predicted and never should have is a real state, not an error.
"""

from __future__ import annotations

import math
from collections.abc import Iterable


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def prf(tp: int, fp: int, fn: int) -> dict:
    """Precision, recall and F1 from the three counts a confusion matrix gives per class."""
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    f1 = ratio(2 * precision * recall, precision + recall)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "support": tp + fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def macro(per_class: dict[str, dict], classes: Iterable[str]) -> dict[str, float]:
    """The unweighted mean of each metric over the classes, never over the rows: a model that never
    predicts `refuse` must not look good because `refuse` is rare."""
    names = tuple(classes)
    return {
        metric: sum(per_class[name][metric] for name in names) / len(names) if names else 0.0
        for metric in ("precision", "recall", "f1")
    }


def percentile(values: list[float], fraction: float) -> float:
    """The nearest-rank percentile, which needs no interpolation and is stable for small samples."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]
