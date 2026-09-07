import { describe, expect, it } from "vitest";
import { sanitizeStoredChatMessage } from "@/lib/chat/sanitize";

describe("sanitizeStoredChatMessage", () => {
  it("returns null only for a bad id/role/content/displayOnly", () => {
    expect(sanitizeStoredChatMessage(null)).toBeNull();
    expect(sanitizeStoredChatMessage("x")).toBeNull();
    expect(
      sanitizeStoredChatMessage({ role: "user", content: "hi" }),
    ).toBeNull();
    expect(
      sanitizeStoredChatMessage({ id: 1, role: "user", content: "hi" }),
    ).toBeNull();
    expect(
      sanitizeStoredChatMessage({
        id: "1",
        role: "system",
        content: "hi",
      }),
    ).toBeNull();
    expect(
      sanitizeStoredChatMessage({
        id: "1",
        role: "user",
        content: 3,
      }),
    ).toBeNull();
    expect(
      sanitizeStoredChatMessage({
        id: "1",
        role: "user",
        content: "hi",
        displayOnly: "yes",
      }),
    ).toBeNull();
  });

  it("preserves unknown keys on toolRun, risk, and test_cases", () => {
    const sanitized = sanitizeStoredChatMessage({
      id: "a-1",
      role: "assistant",
      content: "answer",
      toolRun: {
        summary: "s",
        markdown: "",
        calls: [],
        coverage: { covered: 3, total: 5 },
        confidence: 0.82,
        risk: {
          score: 10,
          level: "low",
          rationale: "ok",
          factors: [],
          model_version: "v2",
        },
        test_cases: {
          output_style: "steps",
          cases: [],
          generator: "pack-v3",
        },
      },
    });

    expect(sanitized?.toolRun).toMatchObject({
      summary: "s",
      coverage: { covered: 3, total: 5 },
      confidence: 0.82,
      risk: { model_version: "v2" },
      test_cases: { generator: "pack-v3" },
    });
  });

  it("preserves unknown keys on run (usage, warnings, …)", () => {
    const sanitized = sanitizeStoredChatMessage({
      id: "a-1",
      role: "assistant",
      content: "answer",
      run: {
        request_id: "r1",
        outcome: "success",
        tools: ["t1"],
        usage: { input: 10, output: 20 },
        warnings: ["slow retrieval"],
        retry_count: 2,
      },
    });

    expect(sanitized?.run).toEqual({
      request_id: "r1",
      outcome: "success",
      tools: ["t1"],
      usage: { input: 10, output: 20 },
      warnings: ["slow retrieval"],
      retry_count: 2,
    });
  });

  it("repairs a poisoned leaf without dropping siblings", () => {
    const sanitized = sanitizeStoredChatMessage({
      id: "a-1",
      role: "assistant",
      content: "answer",
      citations: [
        { source_id: "ok", source_type: "pdf", page_label: "3" },
        { source_id: "bad", quote: { nested: true } },
      ],
      toolRun: {
        summary: "s",
        calls: [
          { tool_name: "t", ok: true, summary: "fine" },
          { tool_name: "u", ok: true, summary: { bad: true } },
          null,
        ],
        risk: {
          score: 40,
          level: "medium",
          rationale: "partial",
          factors: [
            { factor_id: "a", weight: 1, note: "keep" },
            null,
            { factor_id: "b" },
          ],
        },
      },
    });

    expect(sanitized?.citations).toEqual([
      { source_id: "ok", source_type: "pdf", page_label: "3" },
    ]);
    expect(sanitized?.toolRun).toMatchObject({
      summary: "s",
      calls: [
        { tool_name: "t", ok: true, summary: "fine" },
        { tool_name: "u", ok: true },
      ],
      risk: {
        score: 40,
        level: "medium",
        rationale: "partial",
        factors: [{ factor_id: "a", weight: 1, note: "keep" }],
      },
    });
  });

  it("drops a malformed projection without taking the message", () => {
    const sanitized = sanitizeStoredChatMessage({
      id: "a-1",
      role: "assistant",
      content: "plain answer",
      citations: {},
      toolsUsed: "nope",
      run: "nope",
      toolRun: "nope",
    });

    expect(sanitized).toEqual({
      id: "a-1",
      role: "assistant",
      content: "plain answer",
    });
  });

  it("drops a non-string tools array on run while keeping other fields", () => {
    const sanitized = sanitizeStoredChatMessage({
      id: "a-1",
      role: "assistant",
      content: "answer",
      run: {
        request_id: "r1",
        tools: "not-an-array",
        usage: { input: 1 },
      },
    });

    expect(sanitized?.run).toEqual({
      request_id: "r1",
      usage: { input: 1 },
    });
  });
});
