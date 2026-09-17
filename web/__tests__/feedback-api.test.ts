import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import {
  clearResponseFeedback,
  upsertResponseFeedback,
} from "@/lib/api/feedback";

describe("response feedback API", () => {
  it("PUTs rating body without prompt fields and optional query metadata", async () => {
    const request = vi.fn().mockResolvedValue({
      request_id: "req-1",
      rating: "positive",
      created_at: "2026-09-17T10:00:00+00:00",
      updated_at: "2026-09-17T10:00:00+00:00",
      tools: [],
    });

    await upsertResponseFeedback({
      baseUrl: "http://127.0.0.1:8000",
      requestId: "req-1",
      conversationId: "conv-1",
      clientMessageId: "a-1",
      body: { rating: "positive" },
      request,
    });

    expect(request).toHaveBeenCalledWith({
      baseUrl: "http://127.0.0.1:8000",
      path: "/api/v1/responses/req-1/feedback?conversation_id=conv-1&client_message_id=a-1",
      method: "PUT",
      body: { rating: "positive" },
      signal: undefined,
      timeoutMs: undefined,
    });
    const body = request.mock.calls[0][0].body as Record<string, unknown>;
    expect(body).not.toHaveProperty("prompt_key");
    expect(body).not.toHaveProperty("prompt_version");
  });

  it("DELETEs feedback by request_id", async () => {
    const request = vi.fn().mockResolvedValue(undefined);
    await clearResponseFeedback({
      baseUrl: "http://127.0.0.1:8000",
      requestId: "req-1",
      request,
    });
    expect(request).toHaveBeenCalledWith({
      baseUrl: "http://127.0.0.1:8000",
      path: "/api/v1/responses/req-1/feedback",
      method: "DELETE",
      signal: undefined,
      timeoutMs: undefined,
    });
  });

  it("GETs feedback by request_id", async () => {
    const { getResponseFeedback } = await import("@/lib/api/feedback");
    const request = vi.fn().mockResolvedValue({
      request_id: "req-1",
      rating: "positive",
    });
    await getResponseFeedback({
      baseUrl: "http://127.0.0.1:8000",
      requestId: "req-1",
      request,
    });
    expect(request).toHaveBeenCalledWith({
      baseUrl: "http://127.0.0.1:8000",
      path: "/api/v1/responses/req-1/feedback",
      method: "GET",
      signal: undefined,
      timeoutMs: undefined,
    });
  });

  it("propagates ApiError", async () => {
    const request = vi.fn().mockRejectedValue(
      new ApiError({
        status: 500,
        title: "Operational error",
        detail: "An unexpected error occurred.",
        code: "operational_error",
      }),
    );
    await expect(
      upsertResponseFeedback({
        baseUrl: "http://127.0.0.1:8000",
        requestId: "req-1",
        body: { rating: "negative", reason: "incorrect" },
        request,
      }),
    ).rejects.toMatchObject({ status: 500 });
  });
});
