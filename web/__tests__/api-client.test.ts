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

  /**
   * Mirrors real `fetch`, which rejects with the aborting signal's *reason* —
   * `TimeoutError` for `AbortSignal.timeout`, `AbortError` for a controller.
   */
  const abortAwareFetch = () =>
    vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          const signal = init?.signal;
          signal?.addEventListener("abort", () => {
            reject(signal.reason);
          });
        }),
    );

  it("aborts with a cancellation error when timeoutMs elapses", async () => {
    vi.stubGlobal("fetch", abortAwareFetch());

    const pending = apiRequest({
      baseUrl: "http://127.0.0.1:8000",
      path: "/health",
      timeoutMs: 10,
    });

    // A real timeout surfaces as TimeoutError, never AbortError.
    await expect(pending).rejects.toMatchObject({
      name: "ApiError",
      code: "aborted",
    });
  });

  it("propagates caller AbortSignal", async () => {
    const controller = new AbortController();
    vi.stubGlobal("fetch", abortAwareFetch());

    const pending = apiRequest({
      baseUrl: "http://127.0.0.1:8000",
      path: "/health",
      signal: controller.signal,
      timeoutMs: 60_000,
    });
    controller.abort();

    await expect(pending).rejects.toMatchObject({
      name: "ApiError",
      code: "aborted",
    });
  });

  it("falls back when AbortSignal.any is unavailable", async () => {
    const controller = new AbortController();
    vi.stubGlobal("fetch", abortAwareFetch());

    // Pre-Safari 17.4 / Firefox 124 have AbortSignal but not AbortSignal.any.
    const originalAny = AbortSignal.any;
    Reflect.deleteProperty(AbortSignal, "any");
    try {
      const pending = apiRequest({
        baseUrl: "http://127.0.0.1:8000",
        path: "/health",
        signal: controller.signal,
        timeoutMs: 60_000,
      });
      controller.abort();

      await expect(pending).rejects.toMatchObject({ code: "aborted" });
    } finally {
      Object.defineProperty(AbortSignal, "any", {
        value: originalAny,
        writable: true,
        configurable: true,
      });
    }
  });

  it("uses a safe generic message for a malformed success body", async () => {
    const toxic = "<html>provider dump sk-abc123 Traceback (most recent call)";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(toxic, {
          status: 200,
          headers: { "Content-Type": "text/html" },
        }),
      ),
    );

    let caught: unknown;
    try {
      await apiRequest({ baseUrl: "http://127.0.0.1:8000", path: "/health" });
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(ApiError);
    const apiError = caught as ApiError;
    expect(apiError.message).not.toMatch(/html|provider dump|sk-abc123/i);
    expect(apiError.detail).not.toMatch(/html|provider dump|sk-abc123/i);
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

  it("JSON-serializes body and sets Content-Type only when body is present", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ answer: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest({
      baseUrl: "http://127.0.0.1:8000",
      path: "/api/v1/chat/ask",
      method: "POST",
      body: { query: "hello", history: [] },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/chat/ask",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ query: "hello", history: [] }),
      }),
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("does not set Content-Type when body is absent", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest({
      baseUrl: "http://127.0.0.1:8000",
      path: "/health",
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBeNull();
  });

  it("passes FormData through without setting Content-Type", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ source_id: "x" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const form = new FormData();
    form.append("file", new Blob(["# hi"]), "spec.md");

    await apiRequest({
      baseUrl: "http://127.0.0.1:8000",
      path: "/api/v1/documents",
      method: "POST",
      body: form,
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.body).toBe(form);
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBeNull();
  });

  it("returns undefined for 204 No Content", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiRequest<undefined>({
      baseUrl: "http://127.0.0.1:8000",
      path: "/api/v1/documents/src-1",
      method: "DELETE",
    });

    expect(result).toBeUndefined();
  });
});
