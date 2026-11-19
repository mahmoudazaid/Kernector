import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type ProjectResponse = components["schemas"]["ProjectResponse"];

export type ListProjectsOptions = {
  /** Same-origin BFF base (empty string) or absolute origin for tests. */
  baseUrl?: string;
  signal?: AbortSignal;
  request?: typeof apiRequest;
};

/**
 * List workspace projects via the Next BFF ``GET /api/v1/projects``.
 */
export async function listProjects(
  options: ListProjectsOptions = {},
): Promise<ProjectResponse[]> {
  const request = options.request ?? apiRequest;
  return request<ProjectResponse[]>({
    baseUrl: options.baseUrl ?? "",
    path: "/api/v1/projects",
    method: "GET",
    signal: options.signal,
  } satisfies ApiRequestOptions);
}
