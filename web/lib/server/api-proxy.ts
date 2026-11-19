/**
 * Server-only upstream URL for Kernector HTTP API (Next BFF routes).
 */

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

export function apiBaseUrl(): string {
  const raw =
    process.env.API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    DEFAULT_API_BASE_URL;
  return raw.replace(/\/+$/, "");
}

export async function proxyApi(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const url = `${apiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(url, { ...init, headers, cache: "no-store" });
}
