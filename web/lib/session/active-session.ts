/**
 * Active conversation pointer (#246).
 *
 * Holds only which conversation (if any) is selected under one versioned key.
 * Transcripts and drafts live in `kernector:conversations:v1`
 * (`web/lib/session/conversations.ts`). Pack-owned surfaces get their own
 * keys (`kernector:pack:…`), never a field here.
 *
 * Pre-#246 payloads stored `{ draft, messages, updatedAt }` here. Those
 * fields are no longer written; `migrateLegacyTranscripts()` reads them once
 * for import into the conversations store.
 *
 * Accessors never throw: private-mode / quota / garbage → null pointer.
 */

/** Versioned active-session key — owned by #14 / #246, domain-neutral. */
export const ACTIVE_SESSION_STORAGE_KEY = "kernector:active-session:v1";

export type ActiveSession = {
  activeConversationId: string | null;
};

function emptySession(): ActiveSession {
  return { activeConversationId: null };
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseActiveSession(value: unknown): ActiveSession | null {
  if (!isPlainObject(value)) {
    return null;
  }
  // Pointer-only shape (#246).
  if ("activeConversationId" in value) {
    const id = value.activeConversationId;
    if (id === null) {
      return { activeConversationId: null };
    }
    if (typeof id === "string" && id.trim()) {
      return { activeConversationId: id };
    }
    return emptySession();
  }
  // Pre-#246 payload still in storage — treat as no pointer until migration
  // moves messages into the conversations store.
  return emptySession();
}

/**
 * Load the active conversation pointer, or null when absent/invalid.
 */
export function loadActiveSession(): ActiveSession {
  try {
    const raw = localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    if (!raw) {
      return emptySession();
    }
    return parseActiveSession(JSON.parse(raw) as unknown) ?? emptySession();
  } catch {
    return emptySession();
  }
}

/**
 * Persist which conversation is selected (`null` = empty `/chat` draft).
 */
export function setActiveConversationId(id: string | null): void {
  try {
    const payload: ActiveSession = {
      activeConversationId: id && id.trim() ? id : null,
    };
    localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Quota / private mode — ignore.
  }
}

/**
 * Subscribe to cross-tab pointer changes (`storage` events).
 */
export function subscribeActiveSession(onChange: () => void): () => void {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  const handler = (event: StorageEvent) => {
    if (event.key === ACTIVE_SESSION_STORAGE_KEY) {
      onChange();
    }
  };
  window.addEventListener("storage", handler);
  return () => window.removeEventListener("storage", handler);
}
