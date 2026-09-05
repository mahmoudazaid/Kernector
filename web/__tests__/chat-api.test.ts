import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import { askChat, CHAT_ASK_TIMEOUT_MS } from "@/lib/api/chat";

describe("askChat", () => {
  it("POSTs the ask body with a long default timeout", async () => {
    const request = vi.fn().mockResolvedValue({
      answer: "ok",
      citations: [],
      tools_used: [],
      run: null,
      tool_run: null,
    });

    await askChat({
      baseUrl: "http://127.0.0.1:8000",
      body: {
        query: "What is the policy?",
        history: [{ role: "user", content: "earlier" }],
        runtime: { provider: "openrouter", model: "m", settings: { temperature: 0.3 } },
      },
      request,
    });

    expect(request).toHaveBeenCalledWith({
      baseUrl: "http://127.0.0.1:8000",
      path: "/api/v1/chat/ask",
      method: "POST",
      body: {
        query: "What is the policy?",
        history: [{ role: "user", content: "earlier" }],
        runtime: { provider: "openrouter", model: "m", settings: { temperature: 0.3 } },
      },
      signal: undefined,
      timeoutMs: CHAT_ASK_TIMEOUT_MS,
    });
    expect(CHAT_ASK_TIMEOUT_MS).toBe(120_000);
  });

  it("propagates ApiError from the request", async () => {
    const request = vi.fn().mockRejectedValue(
      new ApiError({
        status: 502,
        title: "Provider error",
        detail: "The model provider could not complete the request.",
        code: "provider_error",
      }),
    );

    await expect(
      askChat({
        baseUrl: "http://127.0.0.1:8000",
        body: { query: "hello" },
        request,
      }),
    ).rejects.toMatchObject({ status: 502, code: "provider_error" });
  });
});
