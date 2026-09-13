/**
 * Client-side conversation ask coordinator (#246).
 *
 * Captures the originating conversation id for each in-flight ask so a late
 * response always appends to that conversation — even if the user has moved
 * to `/chat` or another thread. Async UI state lives on the conversation
 * record (`runStatus`, `requestStartedAt`, `unread`), not in whichever
 * component is mounted.
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

/** Pending rows newer than this are treated as possibly live in another tab. */
const CROSS_TAB_LIVE_WINDOW_MS = 2 * 60 * 1000;

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
  }));
}

export function hasLiveConversationRun(conversationId: string): boolean {
  if (liveRuns.has(conversationId)) {
    return true;
  }
  // Another tab may own the in-flight ask; shared storage only has timestamps.
  const conversation = getConversation(conversationId);
  if (
    conversation?.runStatus === "pending" &&
    typeof conversation.requestStartedAt === "number"
  ) {
    return Date.now() - conversation.requestStartedAt < CROSS_TAB_LIVE_WINDOW_MS;
  }
  return false;
}

export function interruptStalePendingFromCoordinator(): void {
  interruptStalePendingRuns(hasLiveConversationRun);
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

  liveRuns.add(conversationId);
  updateConversation(conversationId, {
    runStatus: "pending",
    requestStartedAt: Date.now(),
    unread: false,
  });

  try {
    const response = await ask({
      baseUrl,
      body: {
        query,
        history,
        runtime,
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
      unread: false,
    });
    if (failure.kind === "unavailable") {
      return { kind: "unavailable", message: failure.message };
    }
    return { kind: "failed", message: failure.message };
  } finally {
    liveRuns.delete(conversationId);
  }
}

/** Test helper to clear live-run tracking between suites. */
export function resetLiveConversationRunsForTests(): void {
  liveRuns.clear();
}

export type { Conversation };
