import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api/errors";
import type { ChatAskResponse } from "@/lib/api/chat";
import {
  applyTurnResult,
  classifyFailure,
  historyForModel,
  type ChatMessage,
} from "@/lib/chat/turn";

function user(content: string): ChatMessage {
  return { id: "u1", role: "user", content };
}

function assistant(content: string, extras: Partial<ChatMessage> = {}): ChatMessage {
  return { id: "a1", role: "assistant", content, ...extras };
}

describe("historyForModel", () => {
  it("projects role/content and skips display-only rows", () => {
    const messages: ChatMessage[] = [
      user("hello"),
      assistant("Provider failed", { displayOnly: true }),
      assistant("real reply"),
    ];

    expect(historyForModel(messages)).toEqual([
      { role: "user", content: "hello" },
      { role: "assistant", content: "real reply" },
    ]);
  });
});

describe("classifyFailure", () => {
  it("treats 422 as rejected", () => {
    expect(
      classifyFailure(
        new ApiError({
          status: 422,
          title: "Invalid query",
          detail: "refused",
          code: "invalid_query",
        }),
      ),
    ).toEqual({ kind: "rejected", message: "refused" });
  });

  it("treats status 0 as unavailable", () => {
    expect(classifyFailure(ApiError.generic(0))).toEqual({
      kind: "unavailable",
      message: ApiError.generic(0).detail,
    });
  });

  it("treats other statuses as operational", () => {
    expect(
      classifyFailure(
        new ApiError({
          status: 502,
          title: "Provider error",
          detail: "The model provider could not complete the request.",
          code: "provider_error",
        }),
      ),
    ).toEqual({
      kind: "operational",
      message: "The model provider could not complete the request.",
    });
  });
});

describe("applyTurnResult", () => {
  it("appends an assistant row on success", () => {
    const messages = [user("q")];
    const response: ChatAskResponse = {
      answer: "a",
      citations: [
        {
          source_id: "d1",
          source_type: "pdf",
          quote: "q",
          chunk_index: 0,
        },
      ],
      tools_used: [{ tool_name: "t", result_chars: 3 }],
      run: { request_id: "r1", outcome: "success" },
      tool_run: null,
    };

    const next = applyTurnResult(messages, { kind: "success", response });

    expect(next).toHaveLength(2);
    expect(next[1]).toMatchObject({
      role: "assistant",
      content: "a",
      citations: response.citations,
      toolsUsed: response.tools_used,
      run: response.run,
      toolRun: null,
    });
    expect(next[1].displayOnly).toBeUndefined();
  });

  it("drops the user turn on rejection", () => {
    const messages = [user("unsafe")];
    const next = applyTurnResult(messages, {
      kind: "rejected",
      message: "refused",
    });
    expect(next).toEqual([]);
  });

  it("keeps the user turn and adds a display-only error on operational failure", () => {
    const messages = [user("ok query")];
    const next = applyTurnResult(messages, {
      kind: "operational",
      message: "Something went wrong while processing your request.",
    });
    expect(next).toHaveLength(2);
    expect(next[0]).toEqual(user("ok query"));
    expect(next[1]).toMatchObject({
      role: "assistant",
      content: "Something went wrong while processing your request.",
      displayOnly: true,
    });
  });
});
