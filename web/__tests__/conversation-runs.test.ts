import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import type { ChatAskResponse } from "@/lib/api/chat";
import { setActiveConversationId } from "@/lib/session/active-session";
import {
  createConversation,
  getConversation,
  listConversations,
  resetConversationsSnapshotForTests,
} from "@/lib/session/conversations";
import {
  hasLiveConversationRun,
  interruptStalePendingFromCoordinator,
  resetLiveConversationRunsForTests,
  RUN_HEARTBEAT_STALE_MS,
  scheduleStalePendingSweep,
  startConversationRun,
} from "@/lib/session/conversation-runs";

const SUCCESS: ChatAskResponse = {
  answer: "Grounded answer.",
  citations: [],
  tools_used: [],
  run: {
    request_id: "req-1",
    outcome: "success",
    latency_ms: 10,
    model: "test",
    hit_count: 0,
    citation_count: 0,
    tools: [],
  },
  tool_run: null,
};

describe("conversation run coordinator", () => {
  beforeEach(() => {
    localStorage.clear();
    resetConversationsSnapshotForTests();
    resetLiveConversationRunsForTests();
    setActiveConversationId(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("appends a late success to the originating conversation and sets unread when not open", async () => {
    const created = createConversation({
      title: "A",
      messages: [{ id: "u1", role: "user", content: "A question" }],
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
    });
    setActiveConversationId(null);

    let resolveAsk: (value: ChatAskResponse) => void = () => undefined;
    const ask = vi.fn(
      () =>
        new Promise<ChatAskResponse>((resolve) => {
          resolveAsk = resolve;
        }),
    );

    const done = startConversationRun({
      conversationId: created.id,
      query: "A question",
      history: [],
      baseUrl: "http://127.0.0.1:8000",
      ask,
    });

    expect(hasLiveConversationRun(created.id)).toBe(true);
    expect(getConversation(created.id)?.runStatus).toBe("pending");

    resolveAsk(SUCCESS);
    await done;

    const conversation = getConversation(created.id);
    expect(conversation?.runStatus).toBe("idle");
    expect(conversation?.unread).toBe(true);
    expect(conversation?.requestStartedAt).toBeNull();
    expect(conversation?.messages.some((m) => m.role === "assistant")).toBe(
      true,
    );
    expect(hasLiveConversationRun(created.id)).toBe(false);
    expect(listConversations()).toHaveLength(1);
  });

  it("forwards ask body and persists Test Design action", async () => {
    const created = createConversation({
      title: "A",
      messages: [{ id: "u1", role: "user", content: "plan tests" }],
      draft: "",
    });
    setActiveConversationId(created.id);
    const ask = vi.fn(async () => ({
      ...SUCCESS,
      action: {
        kind: "start_workflow" as const,
        workflow_id: "software-delivery.test-design",
        label: "Start Test Design",
        source_locator: {
          provider: "github",
          locator: "mahmoudazaid/Kernector#293",
        },
      },
    }));

    await startConversationRun({
      conversationId: created.id,
      query: "Design tests for mahmoudazaid/Kernector#293",
      history: [],
      baseUrl: "http://127.0.0.1:8000",
      ask,
    });

    expect(ask).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.not.objectContaining({
          source_locator: expect.anything(),
        }),
      }),
    );
    expect(ask).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.objectContaining({
          query: "Design tests for mahmoudazaid/Kernector#293",
        }),
      }),
    );
    expect(getConversation(created.id)?.messages.at(-1)?.action).toEqual({
      kind: "start_workflow",
      workflow_id: "software-delivery.test-design",
      label: "Start Test Design",
      source_locator: {
        provider: "github",
        locator: "mahmoudazaid/Kernector#293",
      },
    });
  });

  it("does not set unread when the originating conversation is still active", async () => {
    const created = createConversation({
      title: "A",
      messages: [{ id: "u1", role: "user", content: "hi" }],
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
    });
    setActiveConversationId(created.id);

    const ask = vi.fn().mockResolvedValue(SUCCESS);
    await startConversationRun({
      conversationId: created.id,
      query: "hi",
      history: [],
      baseUrl: "http://127.0.0.1:8000",
      ask,
    });

    expect(getConversation(created.id)?.unread).toBe(false);
    expect(getConversation(created.id)?.runStatus).toBe("idle");
  });

  it("marks failed on ask error without creating another conversation", async () => {
    const created = createConversation({
      title: "A",
      messages: [{ id: "u1", role: "user", content: "hi" }],
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
    });

    const ask = vi.fn().mockRejectedValue(
      new ApiError({
        status: 502,
        title: "Provider error",
        detail: "boom",
        code: "provider_error",
      }),
    );

    await startConversationRun({
      conversationId: created.id,
      query: "hi",
      history: [],
      baseUrl: "http://127.0.0.1:8000",
      ask,
    });

    expect(listConversations()).toHaveLength(1);
    expect(getConversation(created.id)?.runStatus).toBe("failed");
    expect(getConversation(created.id)?.unread).toBe(false);
    expect(
      getConversation(created.id)?.messages.some((m) =>
        m.content.includes("boom"),
      ),
    ).toBe(true);
  });

  it("interruptStalePendingFromCoordinator fails pending without a live task", () => {
    const stale = createConversation({
      title: "stale",
      messages: [],
      draft: "",
      runStatus: "pending",
      requestStartedAt: 1,
    });
    interruptStalePendingFromCoordinator();
    expect(getConversation(stale.id)?.runStatus).toBe("failed");
  });

  it("interrupts a recent pending row on cold load without a heartbeat", () => {
    const recent = createConversation({
      title: "reloaded",
      messages: [{ id: "u1", role: "user", content: "hi" }],
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
    });
    expect(hasLiveConversationRun(recent.id)).toBe(false);
    interruptStalePendingFromCoordinator();
    expect(getConversation(recent.id)?.runStatus).toBe("failed");
  });

  it("treats a fresh runHeartbeatAt as live across tabs", () => {
    const recent = createConversation({
      title: "other tab",
      messages: [{ id: "u1", role: "user", content: "hi" }],
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
      runHeartbeatAt: Date.now(),
    });
    expect(hasLiveConversationRun(recent.id)).toBe(true);
    interruptStalePendingFromCoordinator();
    expect(getConversation(recent.id)?.runStatus).toBe("pending");
  });

  it("interrupts after the heartbeat grace window on cold load", () => {
    vi.useFakeTimers();
    const recent = createConversation({
      title: "grace",
      messages: [{ id: "u1", role: "user", content: "hi" }],
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
      runHeartbeatAt: Date.now(),
    });
    const cancel = scheduleStalePendingSweep();
    expect(getConversation(recent.id)?.runStatus).toBe("pending");
    vi.advanceTimersByTime(RUN_HEARTBEAT_STALE_MS);
    expect(getConversation(recent.id)?.runStatus).toBe("failed");
    cancel();
    vi.useRealTimers();
  });
});
