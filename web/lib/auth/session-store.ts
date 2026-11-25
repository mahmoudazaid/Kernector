/**
 * In-memory signed-in auth state (#182).
 * Cleared on logout and account switch; never stores the session cookie.
 */

import type { AuthPreferences, AuthSessionState, AuthUser } from "@/lib/auth/types";

const EMPTY: AuthSessionState = {
  user: null,
  csrfToken: null,
  preferences: null,
};

let state: AuthSessionState = { ...EMPTY };
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) {
    listener();
  }
}

export function getAuthSession(): AuthSessionState {
  return state;
}

export function subscribeAuthSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setAuthSession(next: {
  user: AuthUser;
  csrfToken: string;
  preferences?: AuthPreferences | null;
}): void {
  state = {
    user: next.user,
    csrfToken: next.csrfToken,
    preferences: next.preferences ?? state.preferences,
  };
  emit();
}

export function setAuthPreferences(preferences: AuthPreferences | null): void {
  state = { ...state, preferences };
  emit();
}

/** Clear in-memory user preferences and CSRF (logout / account switch). */
export function clearAuthSession(): void {
  state = { ...EMPTY };
  emit();
}

export function beginAccountSwitch(): void {
  clearAuthSession();
}
