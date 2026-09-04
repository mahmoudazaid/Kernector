import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { getHealth } from "@/lib/api/health";

describe("getHealth", () => {
  it("reports unavailable on network failure", async () => {
    const result = await getHealth({
      baseUrl: "http://127.0.0.1:8000",
      request: async () => {
        throw ApiError.generic(0);
      },
    });

    expect(result.available).toBe(false);
    if (!result.available) {
      expect(result.message).toMatch(/unavailable|failed|try again/i);
      expect(result.message).not.toMatch(/Traceback|stack/i);
    }
  });

  it("reports unavailable on timeout", async () => {
    const result = await getHealth({
      baseUrl: "http://127.0.0.1:8000",
      request: async () => {
        throw ApiError.aborted();
      },
    });

    expect(result.available).toBe(false);
    if (!result.available) {
      expect(result.message).not.toMatch(/Traceback/i);
    }
  });

  it("reports unavailable on non-2xx non-problem failures", async () => {
    const result = await getHealth({
      baseUrl: "http://127.0.0.1:8000",
      request: async () => {
        throw ApiError.generic(500);
      },
    });

    expect(result.available).toBe(false);
    if (!result.available) {
      expect(result.message).not.toContain("provider");
    }
  });

  it("reports unavailable with sanitized problem detail", async () => {
    const result = await getHealth({
      baseUrl: "http://127.0.0.1:8000",
      request: async () => {
        throw new ApiError({
          status: 503,
          title: "Service unavailable",
          detail: "The service is temporarily unavailable.",
          code: "unavailable",
        });
      },
    });

    expect(result).toEqual({
      available: false,
      message: "The service is temporarily unavailable.",
    });
  });

  it("reports available when status is ok", async () => {
    const request = vi.fn().mockResolvedValue({ status: "ok" });

    const result = await getHealth({
      baseUrl: "http://127.0.0.1:8000",
      request,
    });

    expect(result).toEqual({ available: true });
    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        baseUrl: "http://127.0.0.1:8000",
        path: "/health",
        method: "GET",
      }),
    );
  });

  it("reports unavailable when status is not ok", async () => {
    const result = await getHealth({
      baseUrl: "http://127.0.0.1:8000",
      request: async <T>() => ({ status: "degraded" }) as T,
    });

    expect(result.available).toBe(false);
    if (!result.available) {
      expect(result.message).toMatch(/unavailable|not ready/i);
    }
  });
});
