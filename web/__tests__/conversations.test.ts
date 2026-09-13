import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CONVERSATIONS_STORAGE_KEY,
  createConversation,
  deleteConversation,
  getConversation,
  getConversationsSnapshot,
  getServerConversationsSnapshot,
  interruptStalePendingRuns,
  listConversations,
  markConversationRead,
  migrateLegacyTranscripts,
  renameConversation,
  resetConversationsSnapshotForTests,
  subscribeConversations,
  updateConversation,
} from "@/lib/session/conversations";
import { ACTIVE_SESSION_STORAGE_KEY } from "@/lib/session/active-session";
import { CHAT_MESSAGES_STORAGE_KEY } from "@/lib/settings/runtime-settings-storage";

describe("conversation store", () => {
  beforeEach(() => {
    localStorage.clear();
    resetConversationsSnapshotForTests();
    vi.spyOn(Date, "now").mockReturnValue(1_700_000_000_000);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates a conversation and makes it listable and retrievable", () => {
    const created = createConversation({
      title: "First question",
      messages: [{ id: "1", role: "user", content: "First question" }],
      draft: "",
    });

    expect(created.id).toBeTruthy();
    expect(created).toMatchObject({
      title: "First question",
      messages: [{ id: "1", role: "user", content: "First question" }],
      draft: "",
      updatedAt: 1_700_000_000_000,
    });
    expect(getConversation(created.id)).toEqual(created);
    expect(listConversations()).toEqual([created]);
    expect(localStorage.getItem(CONVERSATIONS_STORAGE_KEY)).toBeTruthy();
  });

  it("lists conversations newest-first by updatedAt", () => {
    vi.spyOn(Date, "now").mockReturnValueOnce(100).mockReturnValueOnce(200);
    const older = createConversation({
      title: "older",
      messages: [],
      draft: "",
    });
    const newer = createConversation({
      title: "newer",
      messages: [],
      draft: "",
    });

    expect(listConversations().map((c) => c.id)).toEqual([newer.id, older.id]);
  });

  it("renames a conversation", () => {
    const created = createConversation({
      title: "Old title",
      messages: [],
      draft: "",
    });
    const renamed = renameConversation(created.id, "New title");

    expect(renamed?.title).toBe("New title");
    expect(getConversation(created.id)?.title).toBe("New title");
  });

  it("updates messages and draft on an existing conversation", () => {
    const created = createConversation({
      title: "t",
      messages: [{ id: "1", role: "user", content: "hi" }],
      draft: "",
    });
    vi.spyOn(Date, "now").mockReturnValue(1_700_000_000_500);
    const updated = updateConversation(created.id, {
      messages: [
        { id: "1", role: "user", content: "hi" },
        { id: "2", role: "assistant", content: "hello" },
      ],
      draft: "follow-up",
    });

    expect(updated).toMatchObject({
      id: created.id,
      draft: "follow-up",
      messages: [
        { id: "1", role: "user", content: "hi" },
        { id: "2", role: "assistant", content: "hello" },
      ],
      updatedAt: 1_700_000_000_500,
    });
  });

  it("deletes a conversation so it is no longer retrievable", () => {
    const a = createConversation({ title: "a", messages: [], draft: "" });
    const b = createConversation({ title: "b", messages: [], draft: "" });
    expect(deleteConversation(a.id)).toBe(true);
    expect(getConversation(a.id)).toBeNull();
    expect(listConversations().map((c) => c.id)).toEqual([b.id]);
  });

  it("returns null from get/rename/update and false from delete for unknown ids", () => {
    expect(getConversation("missing")).toBeNull();
    expect(renameConversation("missing", "x")).toBeNull();
    expect(
      updateConversation("missing", { messages: [], draft: "" }),
    ).toBeNull();
    expect(deleteConversation("missing")).toBe(false);
  });

  it("migrates legacy active-session messages into one conversation", () => {
    localStorage.setItem(
      ACTIVE_SESSION_STORAGE_KEY,
      JSON.stringify({
        draft: "half written",
        messages: [{ id: "1", role: "user", content: "legacy turn" }],
        updatedAt: 42,
      }),
    );

    const result = migrateLegacyTranscripts();
    expect(result.migrated).toBe(true);
    expect(result.conversationId).toBeTruthy();

    const listed = listConversations();
    expect(listed).toHaveLength(1);
    expect(listed[0]).toMatchObject({
      id: result.conversationId,
      title: "legacy turn",
      draft: "half written",
      messages: [{ id: "1", role: "user", content: "legacy turn" }],
    });
  });

  it("migrates legacy chat-messages:v1 when the session key is absent", () => {
    localStorage.setItem(
      CHAT_MESSAGES_STORAGE_KEY,
      JSON.stringify([{ id: "1", role: "user", content: "from mirror" }]),
    );

    const result = migrateLegacyTranscripts();
    expect(result.migrated).toBe(true);
    expect(listConversations()[0]).toMatchObject({
      title: "from mirror",
      messages: [{ id: "1", role: "user", content: "from mirror" }],
      draft: "",
    });
  });

  it("prefers active-session messages over the legacy mirror when both exist", () => {
    localStorage.setItem(
      ACTIVE_SESSION_STORAGE_KEY,
      JSON.stringify({
        draft: "d",
        messages: [{ id: "1", role: "user", content: "session wins" }],
        updatedAt: 1,
      }),
    );
    localStorage.setItem(
      CHAT_MESSAGES_STORAGE_KEY,
      JSON.stringify([{ id: "9", role: "user", content: "mirror loses" }]),
    );

    migrateLegacyTranscripts();
    expect(listConversations()[0].messages[0].content).toBe("session wins");
  });

  it("is a no-op when conversations already exist", () => {
    createConversation({
      title: "already",
      messages: [{ id: "1", role: "user", content: "kept" }],
      draft: "",
    });
    localStorage.setItem(
      CHAT_MESSAGES_STORAGE_KEY,
      JSON.stringify([{ id: "2", role: "user", content: "should not import" }]),
    );

    const result = migrateLegacyTranscripts();
    expect(result.migrated).toBe(false);
    expect(listConversations()).toHaveLength(1);
    expect(listConversations()[0].title).toBe("already");
  });

  it("is a no-op when there is nothing to migrate", () => {
    expect(migrateLegacyTranscripts()).toEqual({
      migrated: false,
      conversationId: null,
    });
    expect(listConversations()).toEqual([]);
  });

  it("second migrate after a successful migrate is idempotent", () => {
    localStorage.setItem(
      CHAT_MESSAGES_STORAGE_KEY,
      JSON.stringify([{ id: "1", role: "user", content: "once" }]),
    );
    const first = migrateLegacyTranscripts();
    const second = migrateLegacyTranscripts();

    expect(first.migrated).toBe(true);
    expect(second).toEqual({ migrated: false, conversationId: null });
    expect(listConversations()).toHaveLength(1);
  });

  it("stays quiet when localStorage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("private mode");
    });
    expect(listConversations()).toEqual([]);
    expect(getConversation("x")).toBeNull();
    vi.restoreAllMocks();

    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() =>
      createConversation({ title: "t", messages: [], draft: "" }),
    ).not.toThrow();
  });

  it("defaults runStatus idle, unread false, and null requestStartedAt", () => {
    const created = createConversation({
      title: "t",
      messages: [],
      draft: "",
    });
    expect(created).toMatchObject({
      runStatus: "idle",
      unread: false,
      requestStartedAt: null,
    });
  });

  it("persists pending run metadata and unread on update", () => {
    const created = createConversation({
      title: "t",
      messages: [{ id: "1", role: "user", content: "hi" }],
      draft: "",
    });
    const updated = updateConversation(created.id, {
      runStatus: "pending",
      requestStartedAt: 1_700_000_000_100,
      unread: false,
    });
    expect(updated).toMatchObject({
      runStatus: "pending",
      requestStartedAt: 1_700_000_000_100,
      unread: false,
    });
    expect(getConversation(created.id)?.runStatus).toBe("pending");
  });

  it("markConversationRead clears unread", () => {
    const created = createConversation({
      title: "t",
      messages: [],
      draft: "",
      unread: true,
    });
    markConversationRead(created.id);
    expect(getConversation(created.id)?.unread).toBe(false);
  });

  it("interruptStalePendingRuns marks pending without a live task as failed", () => {
    const live = createConversation({
      title: "live",
      messages: [],
      draft: "",
      runStatus: "pending",
      requestStartedAt: 1,
    });
    const stale = createConversation({
      title: "stale",
      messages: [],
      draft: "",
      runStatus: "pending",
      requestStartedAt: 2,
    });
    interruptStalePendingRuns((id) => id === live.id);
    expect(getConversation(live.id)?.runStatus).toBe("pending");
    expect(getConversation(stale.id)).toMatchObject({
      runStatus: "failed",
      requestStartedAt: null,
    });
  });

  it("notifies same-tab subscribers when the store mutates", () => {
    const onChange = vi.fn();
    const unsubscribe = subscribeConversations(onChange);
    createConversation({ title: "a", messages: [], draft: "" });
    expect(onChange).toHaveBeenCalled();
    unsubscribe();
  });

  it("getConversationsSnapshot is stable until a write", () => {
    createConversation({ title: "a", messages: [], draft: "" });
    const first = getConversationsSnapshot();
    const second = getConversationsSnapshot();
    expect(second).toBe(first);
    createConversation({ title: "b", messages: [], draft: "" });
    expect(getConversationsSnapshot()).not.toBe(first);
  });

  it("getServerConversationsSnapshot returns a stable empty reference", () => {
    expect(getServerConversationsSnapshot()).toBe(
      getServerConversationsSnapshot(),
    );
    expect(getServerConversationsSnapshot()).toEqual([]);
  });
});
