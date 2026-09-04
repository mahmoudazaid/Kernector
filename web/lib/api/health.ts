import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/generated/schema";

type HealthResponse = components["schemas"]["HealthResponse"];

export type HealthAvailability =
  { available: true } | { available: false; message: string };

export type GetHealthOptions = {
  baseUrl: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

const SAFE_UNAVAILABLE = "Backend unavailable.";

/**
 * Probe unversioned ``GET /health`` and map to a safe availability result.
 *
 * ``HealthResponse.status`` is typed as ``string`` in OpenAPI; availability
 * requires a runtime ``status === "ok"`` check.
 */
export async function getHealth(
  options: GetHealthOptions,
): Promise<HealthAvailability> {
  const request = options.request ?? apiRequest;
  try {
    const body = await request<HealthResponse>({
      baseUrl: options.baseUrl,
      path: "/health",
      method: "GET",
      signal: options.signal,
      timeoutMs: options.timeoutMs,
    } satisfies ApiRequestOptions);

    if (body.status === "ok") {
      return { available: true };
    }
    return { available: false, message: "Backend is not ready." };
  } catch (error) {
    if (error instanceof ApiError) {
      return {
        available: false,
        message: error.detail || SAFE_UNAVAILABLE,
      };
    }
    return { available: false, message: SAFE_UNAVAILABLE };
  }
}
