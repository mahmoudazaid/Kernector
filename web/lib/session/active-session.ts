/**
 * Domain-neutral active-session store (#14).
 *
 * Holds the turn in progress — composer draft plus transcript — under one
 * versioned key. Pack payloads on messages stay opaque (`toolRun?: unknown`);
 * shared presentation never interprets Story/Compare vocabulary. Pack-owned
 * surfaces get their own keys (`kernector:pack:…`), never a field here.
 *
 * Accessors never throw: private-mode / quota / garbage → empty session.
 *
 * Legacy `kernector:chat-messages:v1` (#235) is a write-through mirror and a
 * read fallback when the session key is absent or unusable, so a live user's
 * transcript is not orphaned.
 */

import { sanitizeStoredChatMessage } from "@/lib/chat/sanitize";
import {
  CHAT_MESSAGES_STORAGE_KEY,
  type StoredChatMessage,
} from "@/lib/settings/runtime-settings-storage";

/** Versioned active-session key — owned by #14, domain-neutral by contract. */
export const ACTIVE_SESSION_STORAGE_KEY = "kernector:active-session:v1";

export type ActiveSession = {
  draft: string;
  messages: StoredChatMessage[];
  /** Monotonic revision; store derives the next stamp from storage, not the clock. */
  updatedAt: number;
};

function emptySession(): ActiveSession {
  return { draft: "", messages: [], updatedAt: 0 };
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseMessages(value: unknown): StoredChatMessage[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  return value.flatMap((entry) => {
    const sanitized = sanitizeStoredChatMessage(entry);
    return sanitized ? [sanitized] : [];
  });
}

function readUpdatedAt(record: Record<string, unknown>): number {
  return typeof record.updatedAt === "number" && Number.isFinite(record.updatedAt)
    ? record.updatedAt
    : 0;
}

function parseActiveSession(value: unknown): ActiveSession | null {
  if (!isPlainObject(value) || typeof value.draft !== "string") {
    return null;
  }
  const messages = parseMessages(value.messages);
  if (messages === null) {
    return null;
  }
  return {
    draft: value.draft,
    messages,
    updatedAt: readUpdatedAt(value),
  };
}

function loadLegacyMessages(): StoredChatMessage[] {
  try {
    const raw = localStorage.getItem(CHAT_MESSAGES_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed: unknown = JSON.parse(raw);
    return parseMessages(parsed) ?? [];
  } catch {
    return [];
  }
}

function readStoredSession(): ActiveSession | null {
  try {
    const raw = localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    return parseActiveSession(JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}

/**
 * Load the active session, or an empty session when absent/invalid.
 *
 * When the #14 session key is missing or unusable, falls back to the #235
 * transcript key with an empty draft so pre-#14 visits keep their conversation.
 */
export function loadActiveSession(): ActiveSession {
  try {
    const raw = localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    if (!raw) {
      return { draft: "", messages: loadLegacyMessages(), updatedAt: 0 };
    }
    const parsed: unknown = JSON.parse(raw);
    const session = parseActiveSession(parsed);
    if (session) {
      return session;
    }
    return { draft: "", messages: loadLegacyMessages(), updatedAt: 0 };
  } catch {
    return { draft: "", messages: loadLegacyMessages(), updatedAt: 0 };
  }
}

/**
 * Persist draft + transcript for the next visit / remount.
 *
 * Derives a monotonic `updatedAt` from storage so wall-clock skew cannot wedge
 * writes permanently. Refuses when the caller's stamp is older than storage
 * (`null`). Dual-writes `messages` to `CHAT_MESSAGES_STORAGE_KEY` as a
 * write-through mirror. Returns the stamp written, or `null` when refused.
 */
export function saveActiveSession(session: ActiveSession): number | null {
  try {
    const stored = readStoredSession();
    if (stored && stored.updatedAt > session.updatedAt) {
      return null;
    }
    const updatedAt = Math.max(
      session.updatedAt,
      (stored?.updatedAt ?? 0) + 1,
    );
    const payload = {
      draft: session.draft,
      messages: session.messages,
      updatedAt,
    };
    localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, JSON.stringify(payload));
    localStorage.setItem(
      CHAT_MESSAGES_STORAGE_KEY,
      JSON.stringify(session.messages),
    );
    return updatedAt;
  } catch {
    // Quota / private mode — ignore; in-memory UI state still works.
    return session.updatedAt;
  }
}

/**
 * Persist only the draft via read-modify-write (does not republish messages).
 * Returns the stamp written, or `null` when skipped because a newer revision
 * already owns the transcript.
 */
export function saveActiveSessionDraft(
  draft: string,
  updatedAt: number,
): number | null {
  try {
    const stored = readStoredSession() ?? emptySession();
    if (stored.updatedAt > updatedAt) {
      return null;
    }
    const nextUpdatedAt = Math.max(updatedAt, stored.updatedAt + 1);
    const payload = {
      draft,
      messages: stored.messages,
      updatedAt: nextUpdatedAt,
    };
    localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, JSON.stringify(payload));
    return nextUpdatedAt;
  } catch {
    return updatedAt;
  }
}

/**
 * Subscribe to cross-tab session changes (`storage` events).
 */
export function subscribeActiveSession(onChange: () => void): () => void {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  const handler = (event: StorageEvent) => {
    if (
      event.key === ACTIVE_SESSION_STORAGE_KEY ||
      event.key === CHAT_MESSAGES_STORAGE_KEY
    ) {
      onChange();
    }
  };
  window.addEventListener("storage", handler);
  return () => window.removeEventListener("storage", handler);
}
