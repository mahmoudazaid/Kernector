/**
 * Server-only proxy helpers for Admin MCP APIs (#324).
 * Reads ``ADMIN_API_TOKEN`` from process env — never expose to the browser.
 */

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

export function adminApiBaseUrl(): string {
  const raw =
    process.env.API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    DEFAULT_API_BASE_URL;
  return raw.replace(/\/+$/, "");
}

export function requireAdminApiToken(): string {
  const token = (process.env.ADMIN_API_TOKEN ?? "").trim();
  if (!token) {
    throw new Error("ADMIN_API_TOKEN is required and must be non-blank");
  }
  return token;
}

export async function proxyAdminMcp(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = requireAdminApiToken();
  const url = `${adminApiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(url, { ...init, headers, cache: "no-store" });
}
