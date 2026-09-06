import { describe, expect, it } from "vitest";
import { evaluateInputLength } from "@/lib/chat/input-length";

describe("evaluateInputLength", () => {
  it("counts a draft against the server-supplied limit", () => {
    expect(evaluateInputLength("hello", 20)).toEqual({
      length: 5,
      maxInputLength: 20,
      exceeded: false,
      counterLabel: "5 / 20 characters",
      guidance: null,
    });
  });

  it("counts the trimmed draft, because trimmed text is what is sent", () => {
    const padded = `  ${"a".repeat(20)}  `;

    expect(evaluateInputLength(padded, 20)).toEqual({
      length: 20,
      maxInputLength: 20,
      exceeded: false,
      counterLabel: "20 / 20 characters",
      guidance: null,
    });
  });

  it("reports the limit and the corrective action when the draft is over", () => {
    expect(evaluateInputLength("abcdefghijkl", 10)).toEqual({
      length: 12,
      maxInputLength: 10,
      exceeded: true,
      counterLabel: "12 / 10 characters",
      guidance: "Message must be at most 10 characters; remove 2 to send.",
    });
  });

  it("accepts a draft that is exactly at the limit", () => {
    expect(evaluateInputLength("abcdefghij", 10).exceeded).toBe(false);
  });
});
