import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type OllamaStatusResponse = components["schemas"]["OllamaStatusResponse"];

export type GetOllamaStatusOptions = {
  baseUrl: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

/**
 * Probe configured Ollama reachability via ``GET /api/v1/ollama/status``.
 */
export async function getOllamaStatus(
  options: GetOllamaStatusOptions,
): Promise<OllamaStatusResponse> {
  const request = options.request ?? apiRequest;
  return request<OllamaStatusResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/ollama/status",
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}
