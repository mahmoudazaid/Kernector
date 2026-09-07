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
 * Legacy `kernector:chat-messages:v1` (#235) remains readable and is dual-written
 * on save so a live user's transcript is not orphaned.
 */

import {
  CHAT_MESSAGES_STORAGE_KEY,
  type StoredChatMessage,
} from "@/lib/runtime-settings-storage";

/** Versioned active-session key — owned by #14, domain-neutral by contract. */
export const ACTIVE_SESSION_STORAGE_KEY = "kernector:active-session:v1";

export type ActiveSession = {
  draft: string;
  messages: StoredChatMessage[];
};

const EMPTY_SESSION: ActiveSession = { draft: "", messages: [] };

function isStoredChatMessage(value: unknown): value is StoredChatMessage {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record.id === "string" &&
    (record.role === "user" || record.role === "assistant") &&
    typeof record.content === "string" &&
    (record.displayOnly === undefined ||
      typeof record.displayOnly === "boolean")
  );
}

function parseMessages(value: unknown): StoredChatMessage[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  return value.every(isStoredChatMessage) ? value : null;
}

function isActiveSession(value: unknown): value is ActiveSession {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  if (typeof record.draft !== "string") {
    return false;
  }
  const messages = parseMessages(record.messages);
  return messages !== null;
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

/**
 * Load the active session, or an empty session when absent/invalid.
 *
 * When the #14 session key is missing, falls back to the #235 transcript key
 * with an empty draft so pre-#14 visits keep their conversation.
 */
export function loadActiveSession(): ActiveSession {
  try {
    const raw = localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    if (raw != null) {
      try {
        const parsed: unknown = JSON.parse(raw);
        if (isActiveSession(parsed)) {
          return { draft: parsed.draft, messages: parsed.messages };
        }
        return { ...EMPTY_SESSION, messages: [] };
      } catch {
        return { ...EMPTY_SESSION, messages: [] };
      }
    }
    return { draft: "", messages: loadLegacyMessages() };
  } catch {
    return { ...EMPTY_SESSION, messages: [] };
  }
}

/**
 * Persist draft + transcript for the next visit / remount.
 *
 * Dual-writes `messages` to `CHAT_MESSAGES_STORAGE_KEY` in the same array shape
 * #235 wrote, so the legacy key stays byte-compatible.
 */
export function saveActiveSession(session: ActiveSession): void {
  try {
    localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, JSON.stringify(session));
    localStorage.setItem(
      CHAT_MESSAGES_STORAGE_KEY,
      JSON.stringify(session.messages),
    );
  } catch {
    // Quota / private mode — ignore; in-memory UI state still works.
  }
}

/**
 * Clear the active session (New chat). Leaves runtime settings alone.
 */
export function clearActiveSession(): void {
  try {
    localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
    localStorage.removeItem(CHAT_MESSAGES_STORAGE_KEY);
  } catch {
    // ignore
  }
}
