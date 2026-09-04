import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiRequest } from "@/lib/api/client";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("apiRequest", () => {
  it("returns parsed JSON on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const body = await apiRequest<{ status: string }>({
      baseUrl: "http://127.0.0.1:8000",
      path: "/health",
    });

    expect(body).toEqual({ status: "ok" });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/health",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("aborts when timeoutMs elapses", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          const signal = init?.signal;
          if (signal) {
            signal.addEventListener("abort", () => {
              reject(new DOMException("Aborted", "AbortError"));
            });
          }
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const pending = apiRequest({
      baseUrl: "http://127.0.0.1:8000",
      path: "/health",
      timeoutMs: 10,
    });

    const expectation = expect(pending).rejects.toThrow(ApiError);
    await vi.advanceTimersByTimeAsync(15);
    await expectation;
  });

  it("propagates caller AbortSignal", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const pending = apiRequest({
      baseUrl: "http://127.0.0.1:8000",
      path: "/health",
      signal: controller.signal,
      timeoutMs: 60_000,
    });
    controller.abort();

    await expect(pending).rejects.toThrow(ApiError);
  });

  it("maps application/problem+json to ApiError without leaking raw body", async () => {
    const problem = {
      type: "https://kernector.dev/problems/not-found",
      title: "Not found",
      status: 404,
      detail: "The requested resource was not found.",
      code: "not_found",
      request_id: "req-1",
      errors: null,
      instance: "/missing",
    };
    const raw = JSON.stringify({
      ...problem,
      stack: "Traceback (most recent call last):\n  File ...",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(raw, {
          status: 404,
          headers: { "Content-Type": "application/problem+json" },
        }),
      ),
    );

    let caught: unknown;
    try {
      await apiRequest({
        baseUrl: "http://127.0.0.1:8000",
        path: "/missing",
      });
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(ApiError);
    const apiError = caught as ApiError;
    expect(apiError.status).toBe(404);
    expect(apiError.title).toBe("Not found");
    expect(apiError.detail).toBe("The requested resource was not found.");
    expect(apiError.code).toBe("not_found");
    expect(apiError.requestId).toBe("req-1");
    expect(apiError.message).not.toMatch(/Traceback|stack/i);
    expect(JSON.stringify(apiError)).not.toMatch(/Traceback/);
  });

  it("uses a safe generic message for non-JSON error bodies", async () => {
    const toxic = "INTERNAL: provider dump\nTraceback (most recent call last)";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(toxic, {
          status: 500,
          headers: { "Content-Type": "text/plain" },
        }),
      ),
    );

    let caught: unknown;
    try {
      await apiRequest({
        baseUrl: "http://127.0.0.1:8000",
        path: "/health",
      });
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(ApiError);
    const apiError = caught as ApiError;
    expect(apiError.message).not.toContain("Traceback");
    expect(apiError.message).not.toContain("provider dump");
    expect(apiError.detail).not.toContain("Traceback");
    expect(apiError.status).toBe(500);
  });
});
