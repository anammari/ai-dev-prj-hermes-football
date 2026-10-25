import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FreshnessBanner } from "./FreshnessBanner";
import type { Freshness } from "@/lib/api/client";

const REPORT: Freshness = {
  as_of: "2026-10-25T05:00:00Z",
  overall_status: "stale",
  max_age_minutes: 1500,
  next_scheduled_run_at: "2026-10-26T02:00:00Z",
  competitions: [],
} as Freshness;

describe("FreshnessBanner", () => {
  it("names the age and the source on screen", () => {
    render(<FreshnessBanner freshness={REPORT} />);
    expect(screen.getByText("stale")).toBeInTheDocument();
    expect(screen.getByText("25 Oct 2026, 05:00 UTC")).toBeInTheDocument();
    expect(screen.getByText("hermes-football ingestion ledger")).toBeInTheDocument();
    expect(screen.getByText(/oldest refresh 1d 1h/)).toBeInTheDocument();
  });

  it("does not invent a timestamp when the report has none", () => {
    render(<FreshnessBanner freshness={{ ...REPORT, as_of: null } as unknown as Freshness} />);
    expect(screen.getByText("unknown")).toBeInTheDocument();
  });
});
