import { describe, expect, it } from "vitest";
import { formatTimestamp } from "@/lib/format/timestamp";

describe("formatTimestamp", () => {
  it("formats local wall clock as DD Mon YYYY, HH:MM AM/PM", () => {
    const local = new Date(2026, 8, 9, 9, 35);
    expect(formatTimestamp(local.toISOString())).toBe("09 Sep 2026, 09:35 AM");
  });

  it("uses 12-hour noon and midnight", () => {
    expect(formatTimestamp(new Date(2026, 0, 1, 0, 5).toISOString())).toBe(
      "01 Jan 2026, 12:05 AM",
    );
    expect(formatTimestamp(new Date(2026, 0, 1, 12, 0).toISOString())).toBe(
      "01 Jan 2026, 12:00 PM",
    );
  });

  it("returns invalid input unchanged", () => {
    expect(formatTimestamp("not-a-date")).toBe("not-a-date");
  });
});
