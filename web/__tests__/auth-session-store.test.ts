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
    const generationBefore = getAuthSession().generation;
    clearAuthSession();
    expect(getAuthSession()).toEqual({
      user: null,
      csrfToken: null,
      preferences: null,
      generation: generationBefore + 1,
      preferencesStatus: "ready",
    });
  });

  it("keeps the live session on beginAccountSwitch until login succeeds", () => {
    setAuthSession({
      user: { user_id: "usr_1", username: "alice" },
      csrfToken: "csrf-a",
    });
    setAuthPreferences({
      provider: "openrouter",
      model: "model-a",
      usable: true,
    });
    const before = getAuthSession();
    const nextGen = beginAccountSwitch();
    expect(nextGen).toBe(before.generation + 1);
    expect(getAuthSession().user).toEqual(before.user);
    expect(getAuthSession().csrfToken).toBe("csrf-a");
    expect(getAuthSession().preferences).toEqual({
      provider: "openrouter",
      model: "model-a",
      usable: true,
    });
    expect(getAuthSession().generation).toBe(nextGen);
  });

  it("ignores preference updates from a stale generation", () => {
    setAuthSession({
      user: { user_id: "usr_1", username: "alice" },
      csrfToken: "csrf-a",
      preferences: null,
      preferencesStatus: "loading",
    });
    const generation = getAuthSession().generation;
    beginAccountSwitch();
    setAuthPreferences(
      { provider: "ollama", model: "stale", usable: true },
      { generation, status: "ready" },
    );
    expect(getAuthSession().preferences).toBeNull();
    expect(getAuthSession().preferencesStatus).toBe("loading");
  });
});
