import { describe, expect, it } from "vitest";

import { runDetailLines } from "@/lib/chat/run-details";

describe("runDetailLines tokens (#49)", () => {
  it("returns no lines for null or undefined run", () => {
    expect(runDetailLines(null)).toEqual([]);
    expect(runDetailLines(undefined)).toEqual([]);
  });

  it("renders zero total tokens", () => {
    expect(runDetailLines({ total_tokens: 0 })).toContain("Tokens: 0");
  });

  it("renders prompt-only tokens", () => {
    expect(runDetailLines({ prompt_tokens: 700 })).toContain("Tokens: 700 in");
  });

  it("renders completion-only tokens", () => {
    expect(runDetailLines({ completion_tokens: 200 })).toContain(
      "Tokens: 200 out",
    );
  });

  it("renders in/out without total", () => {
    expect(
      runDetailLines({ prompt_tokens: 700, completion_tokens: 200 }),
    ).toContain("Tokens: 700 in / 200 out");
  });

  it("renders breakdown alongside total", () => {
    expect(
      runDetailLines({
        prompt_tokens: 700,
        completion_tokens: 200,
        total_tokens: 900,
      }),
    ).toContain("Tokens: 700 in / 200 out (900 total)");
  });

  it("renders total-only tokens", () => {
    expect(runDetailLines({ total_tokens: 900 })).toContain("Tokens: 900");
  });
});

describe("runDetailLines cost (#49)", () => {
  it("shows reported cost without inventing currency", () => {
    expect(runDetailLines({ cost: 0.0012 })).toContain("Cost: 0.0012");
  });

  it("shows local no-cost caption for ollama when cost is missing", () => {
    expect(runDetailLines({ provider: "ollama" })).toContain(
      "Cost: local (no API cost)",
    );
  });

  it("shows N/A for openrouter when cost is missing", () => {
    expect(runDetailLines({ provider: "openrouter" })).toContain("Cost: N/A");
  });

  it("shows N/A when tokens exist without cost or provider", () => {
    expect(runDetailLines({ total_tokens: 12 })).toContain("Cost: N/A");
  });

  it("shows cost without tokens when only cost is present", () => {
    const lines = runDetailLines({ cost: 0.5 });
    expect(lines).toContain("Cost: 0.5");
    expect(lines.some((line) => line.startsWith("Tokens:"))).toBe(false);
  });

  it("prefers reported cost over provider fallback", () => {
    expect(
      runDetailLines({ provider: "ollama", cost: 0 }),
    ).toContain("Cost: 0");
  });
});
