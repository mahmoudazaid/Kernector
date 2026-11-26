/** Same-origin BFF calls for auth and preferences (#182). */

import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AuthPreferences, AuthUser } from "@/lib/auth/types";

export type MeResponse = AuthUser & { csrf_token: string };

export type AuthApiOptions = {
  /** Same-origin BFF base (empty string) or absolute origin for tests. */
  baseUrl?: string;
  signal?: AbortSignal;
  request?: typeof apiRequest;
};

const BFF = "";

function opts(options: AuthApiOptions = {}): {
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

export async function loginRequest(
  username: string,
  password: string,
  options: AuthApiOptions = {},
): Promise<MeResponse> {
  const { baseUrl, request, signal } = opts(options);
  return request<MeResponse>({
    baseUrl,
    path: "/api/v1/auth/login",
    method: "POST",
    body: { username, password },
    signal,
  } satisfies ApiRequestOptions);
}

export async function meRequest(
  options: AuthApiOptions = {},
): Promise<MeResponse | null> {
  const { baseUrl, request, signal } = opts(options);
  try {
    return await request<MeResponse>({
      baseUrl,
      path: "/api/v1/auth/me",
      method: "GET",
      signal,
      headers: { "Cache-Control": "no-store" },
    } satisfies ApiRequestOptions);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }
    throw error;
  }
}

export async function logoutRequest(
  csrfToken: string,
  options: AuthApiOptions = {},
): Promise<void> {
  const { baseUrl, request, signal } = opts(options);
  await request<void>({
    baseUrl,
    path: "/api/v1/auth/logout",
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    signal,
  } satisfies ApiRequestOptions);
}

export async function getPreferencesRequest(
  options: AuthApiOptions = {},
): Promise<AuthPreferences> {
  const { baseUrl, request, signal } = opts(options);
  return request<AuthPreferences>({
    baseUrl,
    path: "/api/v1/me/preferences",
    method: "GET",
    signal,
    headers: { "Cache-Control": "no-store" },
  } satisfies ApiRequestOptions);
}

export async function putPreferencesRequest(
  csrfToken: string,
  provider: string,
  model: string,
  options: AuthApiOptions = {},
): Promise<AuthPreferences> {
  const { baseUrl, request, signal } = opts(options);
  return request<AuthPreferences>({
    baseUrl,
    path: "/api/v1/me/preferences",
    method: "PUT",
    headers: { "X-CSRF-Token": csrfToken },
    body: { provider, model },
    signal,
  } satisfies ApiRequestOptions);
}
