import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type RuntimeSettingsResponse =
  components["schemas"]["RuntimeSettingsResponse"];

export type GetRuntimeSettingsOptions = {
  baseUrl: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

/**
 * Load the provider/model/settings catalog from ``GET /api/v1/settings``.
 */
export async function getRuntimeSettings(
  options: GetRuntimeSettingsOptions,
): Promise<RuntimeSettingsResponse> {
  const request = options.request ?? apiRequest;
  return request<RuntimeSettingsResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/settings",
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}
