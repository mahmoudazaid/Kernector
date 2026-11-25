/** Same-origin BFF calls for auth and preferences (#182). */

import type { AuthPreferences, AuthUser } from "@/lib/auth/types";

export type MeResponse = AuthUser & { csrf_token: string };

async function parseJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

export async function loginRequest(
  username: string,
  password: string,
): Promise<MeResponse> {
  const response = await fetch("/api/v1/auth/login", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      Origin: window.location.origin,
    },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    throw new Error("Sign-in failed");
  }
  return parseJson<MeResponse>(response);
}

export async function meRequest(): Promise<MeResponse | null> {
  const response = await fetch("/api/v1/auth/me", {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
  });
  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new Error("Session check failed");
  }
  return parseJson<MeResponse>(response);
}

export async function logoutRequest(csrfToken: string): Promise<void> {
  const response = await fetch("/api/v1/auth/logout", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrfToken },
  });
  if (!response.ok && response.status !== 204) {
    throw new Error("Sign-out failed");
  }
}

export async function getPreferencesRequest(): Promise<AuthPreferences> {
  const response = await fetch("/api/v1/me/preferences", {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error("Preferences load failed");
  }
  return parseJson<AuthPreferences>(response);
}

export async function putPreferencesRequest(
  csrfToken: string,
  provider: string,
  model: string,
): Promise<AuthPreferences> {
  const response = await fetch("/api/v1/me/preferences", {
    method: "PUT",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify({ provider, model }),
  });
  if (!response.ok) {
    throw new Error("Preferences save failed");
  }
  return parseJson<AuthPreferences>(response);
}
