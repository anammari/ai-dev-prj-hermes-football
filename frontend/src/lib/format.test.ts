import { describe, expect, it } from "vitest";

import {
  formatAge,
  formatDate,
  formatGoalDifference,
  formatPercent,
  formatScore,
  formatTimestamp,
  maskMessage,
  statusTone,
} from "./format";

describe("formatTimestamp", () => {
  it("renders UTC, never the machine's zone", () => {
    expect(formatTimestamp("2026-10-25T04:05:06Z")).toBe("25 Oct 2026, 04:05 UTC");
  });
  it("says unknown rather than inventing a time", () => {
    expect(formatTimestamp(null)).toBe("unknown");
    expect(formatTimestamp(undefined)).toBe("unknown");
    expect(formatTimestamp("not a date")).toBe("unknown");
  });
});

describe("formatAge", () => {
  it("reads as a person would", () => {
    expect(formatAge(9)).toBe("9m");
    expect(formatAge(61)).toBe("1h 1m");
    expect(formatAge(120)).toBe("2h");
    expect(formatAge(26 * 60)).toBe("1d 2h");
    expect(formatAge(0)).toBe("under a minute");
  });
  it("distinguishes never from zero", () => {
    expect(formatAge(null)).toBe("never");
    expect(formatAge(undefined)).toBe("never");
  });
});

describe("numbers", () => {
  it("does not draw an absent metric as zero", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatScore(undefined)).toBe("—");
    expect(formatPercent(0.9599)).toBe("96.0%");
    expect(formatScore(0.9794745)).toBe("0.98");
  });
  it("writes goal difference as a signed integer", () => {
    expect(formatGoalDifference(17)).toBe("+17");
    expect(formatGoalDifference(-3)).toBe("-3");
    expect(formatGoalDifference(0)).toBe("0");
    expect(formatGoalDifference(null)).toBe("—");
  });
  it("formats a date as the date the data describes", () => {
    expect(formatDate("2026-11-01T00:00:00Z")).toBe("2026-11-01");
  });
});

describe("maskMessage", () => {
  it("masks by default and keeps the text when asked", () => {
    expect(maskMessage("where are arsenal in the table", false)).toBe("where are arsenal in the table [masked]");
    expect(maskMessage("where are arsenal in the table", true)).toBe("where are arsenal in the table");
  });
  it("clips a long message before masking", () => {
    const long = "x".repeat(120);
    expect(maskMessage(long, false, 90)).toMatch(/^x{90}… \[masked\]$/);
  });
});

describe("statusTone", () => {
  it("maps the contract's statuses to the four tones", () => {
    expect(statusTone("fresh")).toBe("good");
    expect(statusTone("partial")).toBe("warn");
    expect(statusTone("failed")).toBe("bad");
    expect(statusTone("never")).toBe("neutral");
    expect(statusTone(null)).toBe("neutral");
  });
});
