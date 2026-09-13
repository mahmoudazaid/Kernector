import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ACTIVE_SESSION_STORAGE_KEY,
  loadActiveSession,
  setActiveConversationId,
  subscribeActiveSession,
} from "@/lib/session/active-session";

describe("active session store", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("round-trips the active conversation pointer under the versioned key", () => {
    setActiveConversationId("conv-1");

    expect(loadActiveSession()).toEqual({ activeConversationId: "conv-1" });
    expect(localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)).toBeTruthy();
  });

  it("degrades absent storage to a null pointer", () => {
    expect(loadActiveSession()).toEqual({ activeConversationId: null });
  });

  it("clears the pointer when set to null", () => {
    setActiveConversationId("conv-1");
    setActiveConversationId(null);
    expect(loadActiveSession()).toEqual({ activeConversationId: null });
  });

  it("treats blank ids as null", () => {
    setActiveConversationId("   ");
    expect(loadActiveSession()).toEqual({ activeConversationId: null });
  });

  it("degrades garbage JSON to a null pointer", () => {
    localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, "{not-json");
    expect(loadActiveSession()).toEqual({ activeConversationId: null });
  });

  it("treats pre-#246 draft/messages payloads as no pointer", () => {
    localStorage.setItem(
      ACTIVE_SESSION_STORAGE_KEY,
      JSON.stringify({
        draft: "half",
        messages: [{ id: "1", role: "user", content: "legacy" }],
        updatedAt: 5,
      }),
    );
    expect(loadActiveSession()).toEqual({ activeConversationId: null });
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
    expect(loadActiveSession()).toEqual({ activeConversationId: null });
    vi.restoreAllMocks();

    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => setActiveConversationId("conv-1")).not.toThrow();
  });
});
