/** Client-visible auth session (#182). Session cookie stays HttpOnly. */

export type AuthUser = {
  user_id: string;
  username: string;
};

export type AuthPreferences = {
  provider: string | null;
  model: string | null;
  usable: boolean;
};

/** Whether preferences have been fetched for the current session generation. */
export type PreferencesStatus = "idle" | "loading" | "ready" | "unavailable";

export type AuthSessionState = {
  user: AuthUser | null;
  csrfToken: string | null;
  preferences: AuthPreferences | null;
  /** Monotonic generation; async results must match before applying. */
  generation: number;
  preferencesStatus: PreferencesStatus;
};
