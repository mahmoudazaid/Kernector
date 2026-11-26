/**
 * In-memory signed-in auth state (#182).
 * Cleared on logout and account switch; never stores the session cookie.
 */

import type {
  AuthPreferences,
  AuthSessionState,
  AuthUser,
  PreferencesStatus,
} from "@/lib/auth/types";

const EMPTY: AuthSessionState = {
  user: null,
  csrfToken: null,
  preferences: null,
  generation: 0,
  // Boot as loading until the first /me settles; cleared sessions are "ready".
  preferencesStatus: "loading",
};

const CLEARED: AuthSessionState = {
  ...EMPTY,
  preferencesStatus: "ready",
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

export function bumpAuthGeneration(): number {
  state = {
    ...state,
    generation: state.generation + 1,
  };
  emit();
  return state.generation;
}

export function setAuthSession(next: {
  user: AuthUser;
  csrfToken: string;
  preferences?: AuthPreferences | null;
  preferencesStatus?: PreferencesStatus;
  generation?: number;
}): void {
  const hasPreferences = Object.prototype.hasOwnProperty.call(
    next,
    "preferences",
  );
  state = {
    user: next.user,
    csrfToken: next.csrfToken,
    preferences: hasPreferences
      ? (next.preferences ?? null)
      : state.preferences,
    generation: next.generation ?? state.generation,
    preferencesStatus: next.preferencesStatus ?? state.preferencesStatus,
  };
  emit();
}

export function setAuthPreferences(
  preferences: AuthPreferences | null,
  options: { generation?: number; status?: PreferencesStatus } = {},
): void {
  if (
    options.generation !== undefined &&
    options.generation !== state.generation
  ) {
    return;
  }
  state = {
    ...state,
    preferences,
    preferencesStatus: options.status ?? "ready",
  };
  emit();
}

export function setPreferencesStatus(status: PreferencesStatus): void {
  state = { ...state, preferencesStatus: status };
  emit();
}

/** Clear in-memory user preferences and CSRF (logout / account switch). */
export function clearAuthSession(): void {
  state = {
    ...CLEARED,
    generation: state.generation + 1,
  };
  emit();
}

/**
 * Mark a pending account switch without clearing the live session until login
 * succeeds. Bumps generation so in-flight prefs for the prior user are ignored.
 */
export function beginAccountSwitch(): number {
  return bumpAuthGeneration();
}
