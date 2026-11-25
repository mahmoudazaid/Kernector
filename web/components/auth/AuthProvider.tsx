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
} from "@/lib/api/auth";
import { ApiError } from "@/lib/api/errors";
import {
  beginAccountSwitch,
  clearAuthSession,
  getAuthSession,
  setAuthPreferences,
  setAuthSession,
  setPreferencesStatus,
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
    const generation = getAuthSession().generation;
    setPreferencesStatus("loading");
    try {
      const me = await meRequest();
      if (getAuthSession().generation !== generation) {
        return;
      }
      if (me === null) {
        clearAuthSession();
        return;
      }
      setAuthSession({
        user: { user_id: me.user_id, username: me.username },
        csrfToken: me.csrf_token,
        preferences: null,
        preferencesStatus: "loading",
        generation,
      });
      try {
        const prefs = await getPreferencesRequest();
        setAuthPreferences(prefs, { generation, status: "ready" });
      } catch {
        setAuthPreferences(null, { generation, status: "ready" });
      }
    } catch {
      // Non-401 /me failures must not reject unhandled on every page.
      if (getAuthSession().generation === generation) {
        setPreferencesStatus("ready");
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = useCallback(async (username: string, password: string) => {
    const generation = beginAccountSwitch();
    const me = await loginRequest(username, password);
    if (getAuthSession().generation !== generation) {
      return;
    }
    setAuthSession({
      user: { user_id: me.user_id, username: me.username },
      csrfToken: me.csrf_token,
      preferences: null,
      preferencesStatus: "loading",
      generation,
    });
    try {
      const prefs = await getPreferencesRequest();
      setAuthPreferences(prefs, { generation, status: "ready" });
    } catch {
      setAuthPreferences(null, { generation, status: "ready" });
    }
  }, []);

  const signOut = useCallback(async () => {
    const current = getAuthSession();
    const csrf = current.csrfToken;
    if (!csrf) {
      clearAuthSession();
      return;
    }
    try {
      await logoutRequest(csrf);
      clearAuthSession();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        clearAuthSession();
        return;
      }
      // Keep session so the user can retry; surface the failure.
      throw error;
    }
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
