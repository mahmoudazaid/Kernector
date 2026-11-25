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

export type AuthSessionState = {
  user: AuthUser | null;
  csrfToken: string | null;
  preferences: AuthPreferences | null;
};
