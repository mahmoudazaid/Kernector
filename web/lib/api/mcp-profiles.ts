import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type McpServerInfoResponse =
  components["schemas"]["McpServerInfoResponse"];
export type McpToolCatalogResponse =
  components["schemas"]["McpToolCatalogResponse"];
export type McpAccessProfileResponse =
  components["schemas"]["McpAccessProfileResponse"];
export type McpAccessProfileCreatedResponse =
  components["schemas"]["McpAccessProfileCreatedResponse"];

export type McpAdminApiOptions = {
  /** Same-origin BFF base (empty string) or absolute origin for tests. */
  baseUrl?: string;
  signal?: AbortSignal;
  request?: typeof apiRequest;
};

const BFF = "";

function opts(options: McpAdminApiOptions = {}): {
  baseUrl: string;
  request: typeof apiRequest;
  signal?: AbortSignal;
} {
  return {
    baseUrl: options.baseUrl ?? BFF,
    request: options.request ?? apiRequest,
    signal: options.signal,
  };
}

export async function getMcpServerInfo(
  options: McpAdminApiOptions = {},
): Promise<McpServerInfoResponse> {
  const { baseUrl, request, signal } = opts(options);
  return request<McpServerInfoResponse>({
    baseUrl,
    path: "/api/v1/admin/mcp/server",
    method: "GET",
    signal,
  } satisfies ApiRequestOptions);
}

export async function listMcpTools(
  options: McpAdminApiOptions = {},
): Promise<McpToolCatalogResponse> {
  const { baseUrl, request, signal } = opts(options);
  return request<McpToolCatalogResponse>({
    baseUrl,
    path: "/api/v1/admin/mcp/tools",
    method: "GET",
    signal,
  } satisfies ApiRequestOptions);
}

export async function listMcpProfiles(
  options: McpAdminApiOptions = {},
): Promise<McpAccessProfileResponse[]> {
  const { baseUrl, request, signal } = opts(options);
  return request<McpAccessProfileResponse[]>({
    baseUrl,
    path: "/api/v1/admin/mcp/profiles",
    method: "GET",
    signal,
  } satisfies ApiRequestOptions);
}

export async function createMcpProfile(
  body: {
    project_id: string;
    name: string;
    user_id: string;
    expires_at?: string | null;
    description?: string;
  },
  options: McpAdminApiOptions = {},
): Promise<McpAccessProfileCreatedResponse> {
  const { baseUrl, request, signal } = opts(options);
  return request<McpAccessProfileCreatedResponse>({
    baseUrl,
    path: "/api/v1/admin/mcp/profiles",
    method: "POST",
    body,
    signal,
  } satisfies ApiRequestOptions);
}

export async function updateMcpAllowlist(
  profileId: string,
  allowlist: string[],
  options: McpAdminApiOptions = {},
): Promise<McpAccessProfileResponse> {
  const { baseUrl, request, signal } = opts(options);
  return request<McpAccessProfileResponse>({
    baseUrl,
    path: `/api/v1/admin/mcp/profiles/${encodeURIComponent(profileId)}/allowlist`,
    method: "PUT",
    body: { allowlist },
    signal,
  } satisfies ApiRequestOptions);
}

export async function rotateMcpProfile(
  profileId: string,
  options: McpAdminApiOptions = {},
): Promise<McpAccessProfileCreatedResponse> {
  const { baseUrl, request, signal } = opts(options);
  return request<McpAccessProfileCreatedResponse>({
    baseUrl,
    path: `/api/v1/admin/mcp/profiles/${encodeURIComponent(profileId)}/rotate`,
    method: "POST",
    signal,
  } satisfies ApiRequestOptions);
}

export async function revokeMcpProfile(
  profileId: string,
  options: McpAdminApiOptions = {},
): Promise<McpAccessProfileResponse> {
  const { baseUrl, request, signal } = opts(options);
  return request<McpAccessProfileResponse>({
    baseUrl,
    path: `/api/v1/admin/mcp/profiles/${encodeURIComponent(profileId)}/revoke`,
    method: "POST",
    signal,
  } satisfies ApiRequestOptions);
}

/**
 * Shared mcp.json snippet for Cursor and Claude Code (Streamable HTTP + bearer).
 * The Admin token callout shows this once — do not ship a second client-specific
 * JSON block in the UI. Omit `type`; Cursor treats `url` as HTTP, and Claude Code
 * accepts the same shape. Do not register the same server in both user and
 * project mcp.json — dual createClient races cancel each other in Cursor.
 */
export function mcpClientConfig(endpoint: string, token: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        kernector: {
          url: endpoint,
          headers: {
            Authorization: `Bearer ${token}`,
          },
        },
      },
    },
    null,
    2,
  );
}

/**
 * @deprecated Prefer {@link mcpClientConfig}. Kept for callers that still want
 * an explicit `"type": "http"`; the Admin UI must not show this as a second
 * snippet next to {@link mcpClientConfig}.
 */
export function claudeCodeMcpConfig(endpoint: string, token: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        kernector: {
          type: "http",
          url: endpoint,
          headers: {
            Authorization: `Bearer ${token}`,
          },
        },
      },
    },
    null,
    2,
  );
}

/** @deprecated Use {@link mcpClientConfig}. */
export const cursorMcpConfig = mcpClientConfig;
