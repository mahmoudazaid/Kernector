import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ACTIVE_SESSION_STORAGE_KEY,
  loadActiveSession,
  saveActiveSession,
  saveActiveSessionDraft,
  subscribeActiveSession,
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
    const stamp = saveActiveSession({
      draft: "half-written question",
      messages: [{ id: "1", role: "user", content: "prior turn" }],
      updatedAt: 1,
    });

    expect(loadActiveSession()).toEqual({
      draft: "half-written question",
      messages: [{ id: "1", role: "user", content: "prior turn" }],
      updatedAt: stamp,
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
            toolRun: {
              markdown: { nested: "obj" },
              calls: [],
              coverage: { covered: 3, total: 5 },
              confidence: 0.82,
            },
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
        toolRun: {
          calls: [],
          coverage: { covered: 3, total: 5 },
          confidence: 0.82,
        },
        run: { request_id: "r1" },
      },
    ]);
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

  it("refuses to overwrite storage with a stale observed revision", () => {
    const newer = saveActiveSession({
      draft: "",
      messages: [{ id: "1", role: "user", content: "newer" }],
      updatedAt: 0,
    });
    const refused = saveActiveSession({
      draft: "stale",
      messages: [],
      updatedAt: 0,
    });

    expect(refused).toBeNull();
    expect(loadActiveSession().messages).toEqual([
      { id: "1", role: "user", content: "newer" },
    ]);
    expect(loadActiveSession().updatedAt).toBe(newer);
  });

  it("bumps past a future stamp once the caller adopts the returned revision", () => {
    localStorage.setItem(
      ACTIVE_SESSION_STORAGE_KEY,
      JSON.stringify({
        draft: "",
        messages: [],
        updatedAt: Date.now() + 600_000,
      }),
    );
    const stored = loadActiveSession().updatedAt;
    const refused = saveActiveSession({
      draft: "",
      messages: [{ id: "u-1", role: "user", content: "must persist" }],
      updatedAt: 0,
    });
    expect(refused).toBeNull();
    expect(loadActiveSession().messages).toEqual([]);

    const written = saveActiveSession({
      draft: "",
      messages: [{ id: "u-1", role: "user", content: "must persist" }],
      updatedAt: stored,
    });
    expect(written).toBeGreaterThan(stored);
    expect(loadActiveSession().messages).toEqual([
      { id: "u-1", role: "user", content: "must persist" },
    ]);
  });

  it("bumps the stored revision on every accepted write", () => {
    const first = saveActiveSession({
      draft: "",
      messages: [{ id: "1", role: "user", content: "kept" }],
      updatedAt: 10,
    });
    const second = saveActiveSession({
      draft: "",
      messages: [],
      updatedAt: first!,
    });
    expect(second).toBeGreaterThan(first!);
    expect(loadActiveSession().messages).toEqual([]);
  });

  it("updates only the draft via read-modify-write", () => {
    saveActiveSession({
      draft: "old",
      messages: [{ id: "1", role: "user", content: "kept" }],
      updatedAt: 10,
    });
    const current = loadActiveSession();
    const stamp = saveActiveSessionDraft("new draft", current.updatedAt);
    expect(stamp).toBeGreaterThan(current.updatedAt);
    expect(loadActiveSession()).toEqual({
      draft: "new draft",
      messages: [{ id: "1", role: "user", content: "kept" }],
      updatedAt: stamp,
    });
  });

  it("returns null from draft save when storage is newer", () => {
    const newer = saveActiveSession({
      draft: "tab-b",
      messages: [{ id: "1", role: "user", content: "kept" }],
      updatedAt: 0,
    });
    expect(saveActiveSessionDraft("tab-a", 0)).toBeNull();
    expect(loadActiveSession()).toEqual({
      draft: "tab-b",
      messages: [{ id: "1", role: "user", content: "kept" }],
      updatedAt: newer,
    });
  });

  it("notifies subscribers when another tab writes the session key", () => {
    const onChange = vi.fn();
    const unsubscribe = subscribeActiveSession(onChange);
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: ACTIVE_SESSION_STORAGE_KEY,
        newValue: "{}",
        storageArea: localStorage,
      }),
    );
    expect(onChange).toHaveBeenCalledTimes(1);
    unsubscribe();
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: ACTIVE_SESSION_STORAGE_KEY,
        newValue: "{}",
        storageArea: localStorage,
      }),
    );
    expect(onChange).toHaveBeenCalledTimes(1);
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
  });
});
