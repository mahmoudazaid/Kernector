"use client";

import {
  createContext,
  useCallback,
  useEffect,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import {
  getPreferencesRequest,
  loginRequest,
  logoutRequest,
  meRequest,
} from "@/lib/auth/api";
import {
  beginAccountSwitch,
  clearAuthSession,
  getAuthSession,
  setAuthPreferences,
  setAuthSession,
  subscribeAuthSession,
} from "@/lib/auth/session-store";
import type { AuthSessionState } from "@/lib/auth/types";

type AuthContextValue = AuthSessionState & {
  refresh: () => Promise<void>;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const session = useSyncExternalStore(
    subscribeAuthSession,
    getAuthSession,
    getAuthSession,
  );

  const refresh = useCallback(async () => {
    const me = await meRequest();
    if (me === null) {
      clearAuthSession();
      return;
    }
    setAuthSession({
      user: { user_id: me.user_id, username: me.username },
      csrfToken: me.csrf_token,
    });
    try {
      const prefs = await getPreferencesRequest();
      setAuthPreferences(prefs);
    } catch {
      setAuthPreferences(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = useCallback(async (username: string, password: string) => {
    beginAccountSwitch();
    const me = await loginRequest(username, password);
    setAuthSession({
      user: { user_id: me.user_id, username: me.username },
      csrfToken: me.csrf_token,
      preferences: null,
    });
    try {
      const prefs = await getPreferencesRequest();
      setAuthPreferences(prefs);
    } catch {
      setAuthPreferences(null);
    }
  }, []);

  const signOut = useCallback(async () => {
    const csrf = getAuthSession().csrfToken;
    if (csrf) {
      try {
        await logoutRequest(csrf);
      } catch {
        // Still clear local state.
      }
    }
    clearAuthSession();
  }, []);

  return (
    <AuthContext.Provider
      value={{
        ...session,
        refresh,
        signIn,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
