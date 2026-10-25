import { describe, expect, it } from "vitest";

import { gateList, metricNumber, metricText, perRoute } from "./evals";
import type { EvalRun } from "@/lib/api/client";

const RUN = {
  metrics: {
    routing: {
      macro_f1: 0.9277,
      per_route: { tool: { precision: 1, recall: 0.9, f1: 0.95, support: 10 } },
    },
    retrieval: { recall_at_k: null },
    gates: { false_refusals: [], database_to_notes: ["q-1"] },
  },
} as unknown as EvalRun;

describe("metric readers", () => {
  it("returns null for an unmeasured metric instead of zero", () => {
    expect(metricNumber(RUN, ["routing", "macro_f1"])).toBe(0.9277);
    expect(metricNumber(RUN, ["retrieval", "recall_at_k"])).toBeNull();
    expect(metricNumber(RUN, ["answers", "fact_coverage"])).toBeNull();
  });

  it("reads a string gate and a per-route table", () => {
    expect(metricText(RUN, ["routing", "macro_f1"])).toBeNull();
    expect(perRoute(RUN)).toEqual([{ route: "tool", precision: 1, recall: 0.9, f1: 0.95, support: 10 }]);
    expect(gateList(RUN, "database_to_notes")).toEqual(["q-1"]);
    expect(gateList(RUN, "false_refusals")).toEqual([]);
  });

  it("survives a metrics object of the wrong shape", () => {
    const odd = { metrics: { routing: "nope" } } as unknown as EvalRun;
    expect(metricNumber(odd, ["routing", "macro_f1"])).toBeNull();
    expect(perRoute(odd)).toEqual([]);
  });
});
