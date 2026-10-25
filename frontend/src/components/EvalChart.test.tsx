import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvalChart, macroF1, seriesFrom, TARGET_MACRO_F1 } from "./EvalChart";
import type { EvalRun } from "@/lib/api/client";

function run(overrides: Partial<EvalRun> & { id: string }): EvalRun {
  return {
    set_name: "golden-2026-10-26",
    golden_set_sha256: "a".repeat(64),
    prompt_version: "2",
    model: "clef:cloud",
    git_commit: "4f3bde9",
    source: "live",
    status: "succeeded",
    passed: true,
    metrics: { routing: { macro_f1: 0.95 } },
    failure_reasons: [],
    started_at: "2026-10-25T04:00:00Z",
    finished_at: "2026-10-25T04:05:00Z",
    ...overrides,
  } as EvalRun;
}

describe("seriesFrom", () => {
  it("groups by set name and hash: a different sample is a different line", () => {
    const series = seriesFrom([
      run({ id: "1" }),
      run({ id: "2", set_name: "holdout-2026-10-22", metrics: { routing: { macro_f1: 0.979 } } }),
      run({ id: "3" }),
    ]);
    expect(series.map((line) => line.name)).toEqual([
      "golden-2026-10-26 · aaaaaaaa",
      "holdout-2026-10-22 · aaaaaaaa",
    ]);
    expect(series[0]?.points).toHaveLength(2);
  });

  it("skips a run with no routing metric instead of plotting it at zero", () => {
    const series = seriesFrom([run({ id: "1", metrics: {} })]);
    expect(series).toEqual([]);
  });

  it("orders points by start time", () => {
    const series = seriesFrom([
      run({ id: "late", started_at: "2026-10-25T05:00:00Z" }),
      run({ id: "early", started_at: "2026-10-24T05:00:00Z" }),
    ]);
    expect(series[0]?.points.map((point) => point.run.id)).toEqual(["early", "late"]);
  });
});

describe("macroF1", () => {
  it("reads only a finite number", () => {
    expect(macroF1(run({ id: "1" }))).toBe(0.95);
    expect(macroF1(run({ id: "2", metrics: { routing: { macro_f1: "high" } } }))).toBeNull();
  });
});

describe("EvalChart", () => {
  it("draws the target line and marks a failed run as hollow", () => {
    const { container } = render(
      <EvalChart runs={[run({ id: "1" }), run({ id: "2", passed: false, started_at: "2026-10-26T04:00:00Z" })]} />,
    );
    const dashed = [...container.querySelectorAll("line")].filter((line) => line.getAttribute("stroke-dasharray"));
    expect(dashed).toHaveLength(1);
    expect(screen.getByText(`target ${TARGET_MACRO_F1.toFixed(2)} (dashed)`)).toBeInTheDocument();
    const circles = container.querySelectorAll("circle");
    expect(circles).toHaveLength(2);
    expect(circles[1]?.getAttribute("fill")).toBe("#ffffff");
  });

  it("says what to do when there is no run yet", () => {
    render(<EvalChart runs={[]} />);
    expect(screen.getByText("No scored runs yet.")).toBeInTheDocument();
  });
});
