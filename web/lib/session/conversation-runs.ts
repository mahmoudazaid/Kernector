/**
 * Client-side conversation ask coordinator (#246).
 *
 * Captures the originating conversation id for each in-flight ask so a late
 * response always appends to that conversation — even if the user has moved
 * to `/chat` or another thread. Async UI state lives on the conversation
 * record (`runStatus`, `requestStartedAt`, `runHeartbeatAt`, `unread`), not
 * in whichever component is mounted.
 *
 * Cross-tab liveness uses `runHeartbeatAt`: only a living tab refreshes it.
 * A cold reload stops heartbeating and is swept once the heartbeat goes stale.
 */

import {
  askChat,
  type AskChatOptions,
  type ChatAskResponse,
} from "@/lib/api/chat";
import { ApiError } from "@/lib/api/errors";
import {
  applyTurnResult,
  classifyFailure,
  type ChatMessage,
  type HistoryTurn,
} from "@/lib/chat/turn";
import { loadActiveSession } from "@/lib/session/active-session";
import {
  getConversation,
  interruptStalePendingRuns,
  updateConversation,
  type Conversation,
} from "@/lib/session/conversations";
import type { StoredChatMessage } from "@/lib/settings/runtime-settings-storage";

const liveRuns = new Set<string>();
const heartbeatTimers = new Map<string, ReturnType<typeof setInterval>>();

const HEARTBEAT_INTERVAL_MS = 2_000;
/** Heartbeats older than this are not treated as live (reload / crashed tab). */
export const RUN_HEARTBEAT_STALE_MS = 5_000;

export type StartConversationRunOptions = {
  conversationId: string;
  query: string;
  history: HistoryTurn[];
  baseUrl: string;
  ask?: (options: AskChatOptions) => Promise<ChatAskResponse>;
  /** Optional runtime body forwarded to askChat. */
  runtime?: AskChatOptions["body"]["runtime"];
};

function toChatMessages(
  messages: readonly StoredChatMessage[],
): ChatMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    displayOnly: message.displayOnly,
    citations: message.citations as ChatMessage["citations"],
    toolsUsed: message.toolsUsed as ChatMessage["toolsUsed"],
    run: (message.run as ChatMessage["run"]) ?? null,
    toolRun: (message.toolRun as ChatMessage["toolRun"]) ?? null,
    action: (message.action as ChatMessage["action"]) ?? null,
    pendingApproval:
      (message as { pendingApproval?: ChatMessage["pendingApproval"] })
        .pendingApproval ?? null,
    approvalResolution:
      (message as { approvalResolution?: ChatMessage["approvalResolution"] })
        .approvalResolution ?? null,
  }));
}

function toStored(messages: readonly ChatMessage[]): StoredChatMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    displayOnly: message.displayOnly,
    citations: message.citations,
    toolsUsed: message.toolsUsed,
    run: message.run ?? null,
    toolRun: message.toolRun ?? null,
    action: message.action ?? null,
    pendingApproval: message.pendingApproval ?? null,
    approvalResolution: message.approvalResolution ?? null,
  }));
}

function stopRunHeartbeat(conversationId: string): void {
  const handle = heartbeatTimers.get(conversationId);
  if (handle !== undefined) {
    clearInterval(handle);
    heartbeatTimers.delete(conversationId);
  }
}

function startRunHeartbeat(conversationId: string): void {
  stopRunHeartbeat(conversationId);
  const tick = () => {
    if (!liveRuns.has(conversationId)) {
      stopRunHeartbeat(conversationId);
      return;
    }
    updateConversation(
      conversationId,
      { runHeartbeatAt: Date.now() },
      { touchUpdatedAt: false },
    );
  };
  tick();
  heartbeatTimers.set(
    conversationId,
    setInterval(tick, HEARTBEAT_INTERVAL_MS),
  );
}

export function hasLiveConversationRun(conversationId: string): boolean {
  if (liveRuns.has(conversationId)) {
    return true;
  }
  // Another tab may own the in-flight ask; only a living owner refreshes
  // `runHeartbeatAt`. Recency of `requestStartedAt` alone is not liveness.
  const conversation = getConversation(conversationId);
  if (
    conversation?.runStatus === "pending" &&
    typeof conversation.runHeartbeatAt === "number"
  ) {
    return Date.now() - conversation.runHeartbeatAt < RUN_HEARTBEAT_STALE_MS;
  }
  return false;
}

export function interruptStalePendingFromCoordinator(): void {
  interruptStalePendingRuns(hasLiveConversationRun);
}

/**
 * Sweep now and once more after the heartbeat grace window so a cold reload
 * that lands inside a still-fresh heartbeat self-heals without waiting for
 * another navigation.
 */
export function scheduleStalePendingSweep(): () => void {
  interruptStalePendingFromCoordinator();
  if (typeof window === "undefined") {
    return () => undefined;
  }
  const handle = window.setTimeout(() => {
    interruptStalePendingFromCoordinator();
  }, RUN_HEARTBEAT_STALE_MS);
  return () => window.clearTimeout(handle);
}

export type ConversationRunResult =
  | { kind: "success" }
  | { kind: "rejected"; message: string }
  | { kind: "failed"; message: string }
  | { kind: "unavailable"; message: string }
  | { kind: "missing" };

/**
 * Run one grounded ask against a fixed conversation id.
 *
 * Sets `runStatus: pending` while live, then `idle` + optional `unread` on
 * success, or `failed` on error. Never creates a second conversation.
 */
export async function startConversationRun(
  options: StartConversationRunOptions,
): Promise<ConversationRunResult> {
  const {
    conversationId,
    query,
    history,
    baseUrl,
    ask = askChat,
    runtime = null,
  } = options;

  const existing = getConversation(conversationId);
  if (!existing) {
    return { kind: "missing" };
  }

  const startedAt = Date.now();
  liveRuns.add(conversationId);
  updateConversation(conversationId, {
    runStatus: "pending",
    requestStartedAt: startedAt,
    runHeartbeatAt: startedAt,
    unread: false,
  });
  startRunHeartbeat(conversationId);

  try {
    const response = await ask({
      baseUrl,
      body: {
        query,
        history,
        runtime,
        conversation_id: conversationId,
      },
    });
    const conversation = getConversation(conversationId);
    if (!conversation) {
      return { kind: "missing" };
    }
    const withAnswer = applyTurnResult(toChatMessages(conversation.messages), {
      kind: "success",
      response,
    });
    const activeId = loadActiveSession().activeConversationId;
    updateConversation(conversationId, {
      messages: toStored(withAnswer),
      draft: conversation.draft,
      runStatus: "idle",
      requestStartedAt: null,
      runHeartbeatAt: null,
      unread: activeId !== conversationId,
    });
    return { kind: "success" };
  } catch (error) {
    const conversation = getConversation(conversationId);
    if (!conversation) {
      return { kind: "missing" };
    }
    const apiError = error instanceof ApiError ? error : ApiError.generic(0);
    const failure = classifyFailure(apiError);
    if (failure.kind === "rejected") {
      const next = applyTurnResult(
        toChatMessages(conversation.messages),
        failure,
      );
      updateConversation(conversationId, {
        messages: toStored(next),
        draft: query,
        runStatus: "failed",
        requestStartedAt: null,
        runHeartbeatAt: null,
        unread: false,
      });
      return { kind: "rejected", message: failure.message };
    }
    const next = applyTurnResult(toChatMessages(conversation.messages), failure);
    updateConversation(conversationId, {
      messages: toStored(next),
      draft: conversation.draft,
      runStatus: "failed",
      requestStartedAt: null,
      runHeartbeatAt: null,
      unread: false,
    });
    if (failure.kind === "unavailable") {
      return { kind: "unavailable", message: failure.message };
    }
    return { kind: "failed", message: failure.message };
  } finally {
    stopRunHeartbeat(conversationId);
    liveRuns.delete(conversationId);
  }
}

/** Test helper to clear live-run tracking between suites. */
export function resetLiveConversationRunsForTests(): void {
  for (const conversationId of [...heartbeatTimers.keys()]) {
    stopRunHeartbeat(conversationId);
  }
  liveRuns.clear();
}

export type { Conversation };
