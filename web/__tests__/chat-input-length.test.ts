import { describe, expect, it } from "vitest";
import {
  codePointLength,
  evaluateHistoryLength,
  evaluateInputLength,
} from "@/lib/chat/input-length";

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

  it("counts astral characters as one code point, matching Python len()", () => {
    expect(codePointLength("😀")).toBe(1);
    expect(evaluateInputLength("😀", 1)).toEqual({
      length: 1,
      maxInputLength: 1,
      exceeded: false,
      counterLabel: "1 / 1 characters",
      guidance: null,
    });
    expect(evaluateInputLength("😀😀", 1).exceeded).toBe(true);
  });
});

describe("evaluateHistoryLength", () => {
  it("passes when every history entry is within the limit", () => {
    expect(
      evaluateHistoryLength(
        [
          { content: "short" },
          { content: "also fine" },
        ],
        20,
      ),
    ).toEqual({ exceeded: false, guidance: null });
  });

  it("flags an over-limit prior answer and points the user at New chat", () => {
    expect(
      evaluateHistoryLength(
        [
          { content: "ok" },
          { content: "x".repeat(25) },
        ],
        20,
      ),
    ).toEqual({
      exceeded: true,
      guidance:
        "A previous message exceeds 20 characters. Start a new chat to continue.",
    });
  });
});
