import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type OllamaStatusResponse = components["schemas"]["OllamaStatusResponse"];

export type GetOllamaStatusOptions = {
  baseUrl: string;
  ollamaBaseUrl: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

/**
 * Probe Ollama reachability via ``GET /api/v1/ollama/status``.
 */
export async function getOllamaStatus(
  options: GetOllamaStatusOptions,
): Promise<OllamaStatusResponse> {
  const request = options.request ?? apiRequest;
  const query = new URLSearchParams({ base_url: options.ollamaBaseUrl });
  return request<OllamaStatusResponse>({
    baseUrl: options.baseUrl,
    path: `/api/v1/ollama/status?${query.toString()}`,
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}
