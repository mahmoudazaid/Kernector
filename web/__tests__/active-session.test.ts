import { beforeEach, describe, expect, it } from "vitest";
import {
  ACTIVE_SESSION_STORAGE_KEY,
  clearActiveSession,
  loadActiveSession,
  saveActiveSession,
} from "@/lib/session/active-session";
import { CHAT_MESSAGES_STORAGE_KEY } from "@/lib/runtime-settings-storage";

describe("active session store", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("round-trips draft and messages under the versioned session key", () => {
    saveActiveSession({
      draft: "half-written question",
      messages: [{ id: "1", role: "user", content: "prior turn" }],
    });

    expect(loadActiveSession()).toEqual({
      draft: "half-written question",
      messages: [{ id: "1", role: "user", content: "prior turn" }],
    });
    expect(localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBeTruthy();
  });

  it("degrades absent storage to an empty session", () => {
    expect(loadActiveSession()).toEqual({ draft: "", messages: [] });
  });

  it("degrades garbage JSON to an empty session without throwing", () => {
    localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, "{not-json");
    expect(loadActiveSession()).toEqual({ draft: "", messages: [] });
  });

  it("degrades a partial payload to an empty session", () => {
    localStorage.setItem(
      ACTIVE_SESSION_STORAGE_KEY,
      JSON.stringify({ draft: 12, messages: "nope" }),
    );
    expect(loadActiveSession()).toEqual({ draft: "", messages: [] });
  });

  it("clearActiveSession removes the session and legacy keys", () => {
    saveActiveSession({
      draft: "x",
      messages: [{ id: "1", role: "user", content: "y" }],
    });
    clearActiveSession();
    expect(localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBeNull();
    expect(localStorage.getItem(CHAT_MESSAGES_STORAGE_KEY)).toBeNull();
    expect(loadActiveSession()).toEqual({ draft: "", messages: [] });
  });

  it("keeps the legacy transcript key name exported for compatibility", () => {
    expect(CHAT_MESSAGES_STORAGE_KEY).toBe("kernector:chat-messages:v1");
  });

  it("reads a #235-shaped legacy transcript when the session key is absent", () => {
    const legacy = [
      {
        id: "1",
        role: "user",
        content: "old turn",
        citations: [{ source_id: "d1" }],
        toolRun: { summary: "opaque", calls: [] },
      },
      { id: "2", role: "assistant", content: "reply" },
    ];
    localStorage.setItem(CHAT_MESSAGES_STORAGE_KEY, JSON.stringify(legacy));

    expect(loadActiveSession()).toEqual({
      draft: "",
      messages: legacy,
    });
  });

  it("dual-writes the transcript to the legacy key in #235 payload shape", () => {
    const messages = [
      {
        id: "1",
        role: "user" as const,
        content: "hi",
        toolRun: { summary: "x", calls: [] },
      },
    ];
    saveActiveSession({ draft: "typing", messages });

    expect(
      JSON.parse(localStorage.getItem(CHAT_MESSAGES_STORAGE_KEY)!),
    ).toEqual(messages);
  });
});
