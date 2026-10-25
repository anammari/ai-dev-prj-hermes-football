import type { EvalRun } from "@/lib/api/client";

/**
 * Reading the harness's `metrics` JSON safely.
 *
 * The contract declares `metrics` as an open object: the harness owns its shape (documented in
 * `evals/golden/README.md`) so a new metric does not need a migration. That means the dashboard must
 * narrow it, not cast it. Every accessor here returns `null` for "not measured" - which is a real
 * state (a backfilled routing-only run has no retrieval numbers) - rather than 0.
 */

type Bag = Record<string, unknown>;

function bag(value: unknown): Bag | null {
  return typeof value === "object" && value !== null ? (value as Bag) : null;
}

export function at(run: EvalRun, path: string[]): unknown {
  let current: unknown = run.metrics;
  for (const key of path) {
    const level = bag(current);
    if (!level) return undefined;
    current = level[key];
  }
  return current;
}

export function metricNumber(run: EvalRun, path: string[]): number | null {
  const value = at(run, path);
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function metricText(run: EvalRun, path: string[]): string | null {
  const value = at(run, path);
  return typeof value === "string" ? value : null;
}

export type RouteScore = { route: string; precision: number | null; recall: number | null; f1: number | null; support: number | null };

export function perRoute(run: EvalRun): RouteScore[] {
  const table = bag(at(run, ["routing", "per_route"]));
  if (!table) return [];
  return Object.entries(table).map(([route, value]) => {
    const entry = bag(value) ?? {};
    return {
      route,
      precision: typeof entry.precision === "number" ? entry.precision : null,
      recall: typeof entry.recall === "number" ? entry.recall : null,
      f1: typeof entry.f1 === "number" ? entry.f1 : null,
      support: typeof entry.support === "number" ? entry.support : null,
    };
  });
}

export function gateList(run: EvalRun, key: "false_refusals" | "database_to_notes"): string[] {
  const value = at(run, ["gates", key]);
  return Array.isArray(value) ? value.map(String) : [];
}
