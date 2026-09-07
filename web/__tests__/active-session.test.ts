import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ACTIVE_SESSION_STORAGE_KEY,
  clearActiveSession,
  loadActiveSession,
  saveActiveSession,
  saveActiveSessionDraft,
} from "@/lib/session/active-session";
import { CHAT_MESSAGES_STORAGE_KEY } from "@/lib/settings/runtime-settings-storage";

describe("active session store", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("round-trips draft and messages under the versioned session key", () => {
    saveActiveSession({
      draft: "half-written question",
      messages: [{ id: "1", role: "user", content: "prior turn" }],
      updatedAt: 1,
    });

    expect(loadActiveSession()).toEqual({
      draft: "half-written question",
      messages: [{ id: "1", role: "user", content: "prior turn" }],
      updatedAt: expect.any(Number),
    });
    expect(localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBeTruthy();
  });

  it("degrades absent storage to an empty session", () => {
    expect(loadActiveSession()).toEqual({
      draft: "",
      messages: [],
      updatedAt: 0,
    });
  });

  it("falls back to the legacy transcript when session JSON is garbage", () => {
    const legacy = [{ id: "1", role: "user", content: "kept" }];
    localStorage.setItem(CHAT_MESSAGES_STORAGE_KEY, JSON.stringify(legacy));
    localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, "{not-json");

    expect(loadActiveSession()).toEqual({
      draft: "",
      messages: legacy,
      updatedAt: 0,
    });
    expect(localStorage.getItem(CHAT_MESSAGES_STORAGE_KEY)).toBe(
      JSON.stringify(legacy),
    );
  });

  it("falls back to the legacy transcript when the session payload is partial", () => {
    const legacy = [{ id: "1", role: "user", content: "kept" }];
    localStorage.setItem(CHAT_MESSAGES_STORAGE_KEY, JSON.stringify(legacy));
    localStorage.setItem(
      ACTIVE_SESSION_STORAGE_KEY,
      JSON.stringify({ draft: "x" }),
    );

    expect(loadActiveSession()).toEqual({
      draft: "",
      messages: legacy,
      updatedAt: 0,
    });
  });

  it("keeps valid rows when one message in the session is malformed", () => {
    localStorage.setItem(
      ACTIVE_SESSION_STORAGE_KEY,
      JSON.stringify({
        draft: "still here",
        messages: [
          { id: "1", role: "user", content: "ok" },
          { role: "assistant" },
          { id: "2", role: "assistant", content: "also ok" },
        ],
        updatedAt: 5,
      }),
    );

    expect(loadActiveSession()).toEqual({
      draft: "still here",
      messages: [
        { id: "1", role: "user", content: "ok" },
        { id: "2", role: "assistant", content: "also ok" },
      ],
      updatedAt: 5,
    });
  });

  it("drops poisoned projections instead of accepting them", () => {
    localStorage.setItem(
      ACTIVE_SESSION_STORAGE_KEY,
      JSON.stringify({
        draft: "",
        messages: [
          {
            id: "1",
            role: "assistant",
            content: "hello",
            citations: {},
            toolsUsed: "nope",
            toolRun: { markdown: { nested: "obj" }, calls: [] },
            run: { tools: "not-an-array", request_id: "r1" },
          },
        ],
        updatedAt: 1,
      }),
    );

    expect(loadActiveSession().messages).toEqual([
      {
        id: "1",
        role: "assistant",
        content: "hello",
        toolRun: { calls: [] },
        run: { request_id: "r1" },
      },
    ]);
  });

  it("clearActiveSession removes the session and legacy keys", () => {
    saveActiveSession({
      draft: "x",
      messages: [{ id: "1", role: "user", content: "y" }],
      updatedAt: 1,
    });
    clearActiveSession();
    expect(localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBeNull();
    expect(localStorage.getItem(CHAT_MESSAGES_STORAGE_KEY)).toBeNull();
    expect(loadActiveSession()).toEqual({
      draft: "",
      messages: [],
      updatedAt: 0,
    });
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
        citations: [{ source_id: "d1", source_type: "pdf" }],
        toolRun: { summary: "opaque", calls: [] },
      },
      { id: "2", role: "assistant", content: "reply" },
    ];
    localStorage.setItem(CHAT_MESSAGES_STORAGE_KEY, JSON.stringify(legacy));

    expect(loadActiveSession()).toEqual({
      draft: "",
      messages: legacy,
      updatedAt: 0,
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
    saveActiveSession({ draft: "typing", messages, updatedAt: 1 });

    expect(
      JSON.parse(localStorage.getItem(CHAT_MESSAGES_STORAGE_KEY)!),
    ).toEqual(messages);
  });

  it("refuses to overwrite storage with a stale revision", () => {
    saveActiveSession({
      draft: "",
      messages: [{ id: "1", role: "user", content: "newer" }],
      updatedAt: 100,
    });
    saveActiveSession({
      draft: "stale",
      messages: [],
      updatedAt: 50,
    });

    expect(loadActiveSession().messages).toEqual([
      { id: "1", role: "user", content: "newer" },
    ]);
  });

  it("updates only the draft via read-modify-write", () => {
    saveActiveSession({
      draft: "old",
      messages: [{ id: "1", role: "user", content: "kept" }],
      updatedAt: 10,
    });
    const current = loadActiveSession();
    const stamp = saveActiveSessionDraft("new draft", current.updatedAt);
    expect(stamp).toBeGreaterThanOrEqual(current.updatedAt);
    expect(loadActiveSession()).toEqual({
      draft: "new draft",
      messages: [{ id: "1", role: "user", content: "kept" }],
      updatedAt: stamp,
    });
  });

  it("stays quiet when getItem or setItem throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("private mode");
    });
    expect(loadActiveSession()).toEqual({
      draft: "",
      messages: [],
      updatedAt: 0,
    });
    vi.restoreAllMocks();

    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() =>
      saveActiveSession({
        draft: "x",
        messages: [],
        updatedAt: 1,
      }),
    ).not.toThrow();
    expect(() => clearActiveSession()).not.toThrow();
  });
});
