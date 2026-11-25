import { describe, expect, it, beforeEach } from "vitest";
import {
  beginAccountSwitch,
  clearAuthSession,
  getAuthSession,
  setAuthPreferences,
  setAuthSession,
} from "@/lib/auth/session-store";

describe("auth session store", () => {
  beforeEach(() => {
    clearAuthSession();
  });

  it("clears in-memory user preferences and CSRF on logout", () => {
    setAuthSession({
      user: { user_id: "usr_1", username: "alice" },
      csrfToken: "csrf-a",
      preferences: { provider: "ollama", model: "llama3", usable: true },
    });
    clearAuthSession();
    expect(getAuthSession()).toEqual({
      user: null,
      csrfToken: null,
      preferences: null,
    });
  });

  it("clears state on account switch before new login", () => {
    setAuthSession({
      user: { user_id: "usr_1", username: "alice" },
      csrfToken: "csrf-a",
    });
    setAuthPreferences({
      provider: "openrouter",
      model: "model-a",
      usable: true,
    });
    beginAccountSwitch();
    expect(getAuthSession().preferences).toBeNull();
    expect(getAuthSession().csrfToken).toBeNull();
  });
});
