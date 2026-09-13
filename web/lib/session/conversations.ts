/**
 * Client-local multi-conversation store (#246).
 *
 * Key: `kernector:conversations:v1`
 * Schema: `{ conversations: Conversation[] }` where each conversation has
 * `id`, `title`, `updatedAt` (wall-clock ms for newest-first sort), `messages`,
 * `draft`, `runStatus`, `requestStartedAt`, and `unread`.
 *
 * Migration: `migrateLegacyTranscripts()` once imports a non-empty transcript
 * from the pre-#246 active-session payload (`draft` + `messages`) or the
 * legacy mirror `kernector:chat-messages:v1`. If `conversations` already has
 * rows, migration is a no-op (idempotent). Does not require server auth.
 *
 * Accessors never throw: private-mode / quota / garbage → empty list / null.
 *
 * Subscriptions notify same-tab writes (in-memory listeners) and cross-tab
 * `storage` events — compatible with `useSyncExternalStore` via
 * `getConversationsSnapshot()`.
 */

import { sanitizeStoredChatMessage } from "@/lib/chat/sanitize";
import { ACTIVE_SESSION_STORAGE_KEY } from "@/lib/session/active-session";
import {
  CHAT_MESSAGES_STORAGE_KEY,
  type StoredChatMessage,
} from "@/lib/settings/runtime-settings-storage";

/** Versioned multi-conversation key — owned by #246. */
export const CONVERSATIONS_STORAGE_KEY = "kernector:conversations:v1";

const DEFAULT_TITLE_MAX = 60;

export type ConversationRunStatus = "idle" | "pending" | "failed";

export type Conversation = {
  id: string;
  title: string;
  updatedAt: number;
  messages: StoredChatMessage[];
  draft: string;
  runStatus: ConversationRunStatus;
  requestStartedAt: number | null;
  unread: boolean;
};

export type ConversationWrite = {
  title: string;
  messages: StoredChatMessage[];
  draft: string;
  runStatus?: ConversationRunStatus;
  requestStartedAt?: number | null;
  unread?: boolean;
};

export type ConversationPatch = {
  messages?: StoredChatMessage[];
  draft?: string;
  title?: string;
  runStatus?: ConversationRunStatus;
  requestStartedAt?: number | null;
  unread?: boolean;
};

export type MigrateLegacyResult = {
  migrated: boolean;
  conversationId: string | null;
};

type ConversationsPayload = {
  conversations: Conversation[];
};

const listeners = new Set<() => void>();
let snapshotCache: Conversation[] | null = null;

/** Stable empty list for SSR `useSyncExternalStore` getServerSnapshot. */
const EMPTY_CONVERSATIONS: Conversation[] = [];

/**
 * Cached empty snapshot for hydration — must return the same reference every call.
 */
export function getServerConversationsSnapshot(): Conversation[] {
  return EMPTY_CONVERSATIONS;
}

function notifyListeners(): void {
  for (const listener of listeners) {
    listener();
  }
}

function refreshSnapshot(conversations: Conversation[]): void {
  snapshotCache = conversations.toSorted((a, b) => b.updatedAt - a.updatedAt);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseRunStatus(value: unknown): ConversationRunStatus {
  if (value === "pending" || value === "failed" || value === "idle") {
    return value;
  }
  return "idle";
}

function parseMessages(value: unknown): StoredChatMessage[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((entry) => {
    const sanitized = sanitizeStoredChatMessage(entry);
    return sanitized ? [sanitized] : [];
  });
}

function parseConversation(value: unknown): Conversation | null {
  if (!isPlainObject(value) || typeof value.id !== "string" || !value.id) {
    return null;
  }
  if (typeof value.title !== "string") {
    return null;
  }
  if (typeof value.draft !== "string") {
    return null;
  }
  const updatedAt =
    typeof value.updatedAt === "number" && Number.isFinite(value.updatedAt)
      ? value.updatedAt
      : 0;
  const requestStartedAt =
    typeof value.requestStartedAt === "number" &&
    Number.isFinite(value.requestStartedAt)
      ? value.requestStartedAt
      : null;
  return {
    id: value.id,
    title: value.title,
    draft: value.draft,
    messages: parseMessages(value.messages),
    updatedAt,
    runStatus: parseRunStatus(value.runStatus),
    requestStartedAt,
    unread: value.unread === true,
  };
}

function readPayload(): ConversationsPayload {
  try {
    const raw = localStorage.getItem(CONVERSATIONS_STORAGE_KEY);
    if (!raw) {
      return { conversations: [] };
    }
    const parsed: unknown = JSON.parse(raw);
    if (!isPlainObject(parsed) || !Array.isArray(parsed.conversations)) {
      return { conversations: [] };
    }
    return {
      conversations: parsed.conversations.flatMap((entry) => {
        const conversation = parseConversation(entry);
        return conversation ? [conversation] : [];
      }),
    };
  } catch {
    return { conversations: [] };
  }
}

function writePayload(payload: ConversationsPayload): void {
  try {
    localStorage.setItem(CONVERSATIONS_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Quota / private mode — ignore; caller still holds the in-memory value.
  }
  refreshSnapshot(payload.conversations);
  notifyListeners();
}

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `conv-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Truncate the first user turn into a default title. */
export function titleFromMessages(
  messages: readonly StoredChatMessage[],
  maxLength = DEFAULT_TITLE_MAX,
): string {
  const firstUser = messages.find(
    (message) => message.role === "user" && message.content.trim(),
  );
  if (!firstUser) {
    return "New chat";
  }
  const trimmed = firstUser.content.trim().replace(/\s+/g, " ");
  if (trimmed.length <= maxLength) {
    return trimmed;
  }
  return `${trimmed.slice(0, maxLength - 1).trimEnd()}…`;
}

/**
 * List conversations newest-first by `updatedAt`.
 */
export function listConversations(): Conversation[] {
  return readPayload().conversations.toSorted(
    (a, b) => b.updatedAt - a.updatedAt,
  );
}

/**
 * Stable snapshot for `useSyncExternalStore` (same reference until a write).
 */
export function getConversationsSnapshot(): Conversation[] {
  if (snapshotCache === null) {
    refreshSnapshot(readPayload().conversations);
  }
  return snapshotCache ?? EMPTY_CONVERSATIONS;
}

/**
 * Load one conversation by id, or null when missing/invalid.
 */
export function getConversation(id: string): Conversation | null {
  return readPayload().conversations.find((entry) => entry.id === id) ?? null;
}

/**
 * Persist a new conversation and return it.
 */
export function createConversation(input: ConversationWrite): Conversation {
  const conversation: Conversation = {
    id: newId(),
    title: input.title.trim() || titleFromMessages(input.messages),
    messages: parseMessages(input.messages),
    draft: input.draft,
    updatedAt: Date.now(),
    runStatus: input.runStatus ?? "idle",
    requestStartedAt:
      input.requestStartedAt === undefined ? null : input.requestStartedAt,
    unread: input.unread === true,
  };
  const payload = readPayload();
  payload.conversations.push(conversation);
  writePayload(payload);
  return conversation;
}

/**
 * Rename a conversation; bumps `updatedAt`. Returns null when missing.
 */
export function renameConversation(
  id: string,
  title: string,
): Conversation | null {
  const payload = readPayload();
  const index = payload.conversations.findIndex((entry) => entry.id === id);
  if (index < 0) {
    return null;
  }
  const nextTitle = title.trim() || payload.conversations[index].title;
  const updated: Conversation = {
    ...payload.conversations[index],
    title: nextTitle,
    updatedAt: Date.now(),
  };
  payload.conversations[index] = updated;
  writePayload(payload);
  return updated;
}

/**
 * Patch fields on an existing conversation.
 *
 * Pass `{ touchUpdatedAt: false }` for read-only / draft-only writes that
 * must not reshuffle newest-first ordering.
 */
export function updateConversation(
  id: string,
  patch: ConversationPatch,
  options?: { touchUpdatedAt?: boolean },
): Conversation | null {
  const payload = readPayload();
  const index = payload.conversations.findIndex((entry) => entry.id === id);
  if (index < 0) {
    return null;
  }
  const current = payload.conversations[index];
  const updated: Conversation = {
    ...current,
    messages:
      patch.messages !== undefined
        ? parseMessages(patch.messages)
        : current.messages,
    draft: patch.draft !== undefined ? patch.draft : current.draft,
    title:
      patch.title !== undefined
        ? patch.title.trim() || current.title
        : current.title,
    runStatus:
      patch.runStatus !== undefined ? patch.runStatus : current.runStatus,
    requestStartedAt:
      patch.requestStartedAt !== undefined
        ? patch.requestStartedAt
        : current.requestStartedAt,
    unread: patch.unread !== undefined ? patch.unread : current.unread,
    updatedAt:
      options?.touchUpdatedAt === false ? current.updatedAt : Date.now(),
  };
  payload.conversations[index] = updated;
  writePayload(payload);
  return updated;
}

/**
 * Clear the unread flag when a conversation is opened.
 * Does not bump `updatedAt` — opening is not activity.
 */
export function markConversationRead(id: string): Conversation | null {
  return updateConversation(id, { unread: false }, { touchUpdatedAt: false });
}

const INTERRUPT_MESSAGE =
  "The previous request was interrupted. Please try again.";

/**
 * Pending rows with no live coordinator task are interrupted (failed), not
 * left pretending the request is still running after a full reload.
 */
export function interruptStalePendingRuns(
  hasLiveRun: (conversationId: string) => boolean,
): void {
  const payload = readPayload();
  let changed = false;
  const conversations = payload.conversations.map((entry) => {
    if (entry.runStatus !== "pending" || hasLiveRun(entry.id)) {
      return entry;
    }
    changed = true;
    const alreadyNotified = entry.messages.some(
      (message) =>
        message.role === "assistant" &&
        message.displayOnly &&
        message.content === INTERRUPT_MESSAGE,
    );
    return {
      ...entry,
      runStatus: "failed" as const,
      requestStartedAt: null,
      updatedAt: Date.now(),
      messages: alreadyNotified
        ? entry.messages
        : [
            ...entry.messages,
            {
              id: `interrupt-${entry.id}`,
              role: "assistant" as const,
              content: INTERRUPT_MESSAGE,
              displayOnly: true,
            },
          ],
    };
  });
  if (changed) {
    writePayload({ conversations });
  }
}

/**
 * Remove a conversation. Returns true when something was deleted.
 */
export function deleteConversation(id: string): boolean {
  const payload = readPayload();
  const next = payload.conversations.filter((entry) => entry.id !== id);
  if (next.length === payload.conversations.length) {
    return false;
  }
  writePayload({ conversations: next });
  return true;
}

function readLegacySessionTranscript(): {
  messages: StoredChatMessage[];
  draft: string;
} | null {
  try {
    const raw = localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!isPlainObject(parsed)) {
      return null;
    }
    // Pointer-only active session (#246) has no messages — skip.
    if (!("messages" in parsed)) {
      return null;
    }
    const messages = parseMessages(parsed.messages);
    if (messages.length === 0) {
      return null;
    }
    return {
      messages,
      draft: typeof parsed.draft === "string" ? parsed.draft : "",
    };
  } catch {
    return null;
  }
}

function readLegacyMirrorTranscript(): StoredChatMessage[] {
  try {
    const raw = localStorage.getItem(CHAT_MESSAGES_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    return parseMessages(JSON.parse(raw) as unknown);
  } catch {
    return [];
  }
}

const MIGRATION_DONE_KEY = "kernector:conversations-migrated:v1";

function markMigrationDone(): void {
  try {
    localStorage.setItem(MIGRATION_DONE_KEY, "1");
  } catch {
    // private mode / quota — next visit may retry; still clear when possible
  }
}

function clearLegacyMirror(): void {
  try {
    localStorage.removeItem(CHAT_MESSAGES_STORAGE_KEY);
  } catch {
    // ignore
  }
}

/**
 * Import a single conversation from pre-#246 local transcript keys.
 *
 * Runs at most once per browser profile (marker key). Also clears the legacy
 * mirror so deleting the migrated chat cannot resurrect it on the next visit.
 */
export function migrateLegacyTranscripts(): MigrateLegacyResult {
  try {
    if (localStorage.getItem(MIGRATION_DONE_KEY) === "1") {
      return { migrated: false, conversationId: null };
    }
  } catch {
    return { migrated: false, conversationId: null };
  }

  const existing = readPayload();
  if (existing.conversations.length > 0) {
    clearLegacyMirror();
    markMigrationDone();
    return { migrated: false, conversationId: null };
  }

  const fromSession = readLegacySessionTranscript();
  const messages =
    fromSession?.messages ??
    (() => {
      const mirror = readLegacyMirrorTranscript();
      return mirror.length > 0 ? mirror : null;
    })();

  if (!messages || messages.length === 0) {
    clearLegacyMirror();
    markMigrationDone();
    return { migrated: false, conversationId: null };
  }

  const created = createConversation({
    title: titleFromMessages(messages),
    messages,
    draft: fromSession?.draft ?? "",
  });
  clearLegacyMirror();
  markMigrationDone();
  return { migrated: true, conversationId: created.id };
}

/**
 * Subscribe to conversation store changes (same-tab writes + cross-tab
 * `storage` events).
 */
export function subscribeConversations(onChange: () => void): () => void {
  listeners.add(onChange);
  if (typeof window === "undefined") {
    return () => {
      listeners.delete(onChange);
    };
  }
  const handler = (event: StorageEvent) => {
    if (event.key === CONVERSATIONS_STORAGE_KEY) {
      refreshSnapshot(readPayload().conversations);
      onChange();
    }
  };
  window.addEventListener("storage", handler);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", handler);
  };
}

/** Test helper: drop in-memory snapshot after localStorage.clear(). */
export function resetConversationsSnapshotForTests(): void {
  snapshotCache = null;
}
