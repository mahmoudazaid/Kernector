/**
 * Client-local runtime selections for Settings (#237) and Chat (#235).
 *
 * Keys are shared contracts — do not rename without coordinating both UIs.
 * Ollama base URL is server-owned (`GET /api/v1/settings`); Chat should read it
 * from the catalog, not from this store.
 */

export const RUNTIME_SETTINGS_STORAGE_KEY = "kernector:runtime-settings:v1";

/** Versioned chat transcript key — owned by Chat (#235), not Settings. */
export const CHAT_MESSAGES_STORAGE_KEY = "kernector:chat-messages:v1";

export type StoredRuntimeSettings = {
  provider: string;
  model: string;
  settings: Record<string, number>;
};

export type StoredChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  displayOnly?: boolean;
  citations?: unknown;
  toolsUsed?: unknown;
  run?: unknown;
  toolRun?: unknown;
};

function isStoredRuntimeSettings(value: unknown): value is StoredRuntimeSettings {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  if (
    typeof record.provider !== "string" ||
    typeof record.model !== "string" ||
    typeof record.settings !== "object" ||
    record.settings === null ||
    Array.isArray(record.settings)
  ) {
    return false;
  }
  return Object.values(record.settings as Record<string, unknown>).every(
    (entry) => typeof entry === "number" && Number.isFinite(entry),
  );
}

function isStoredChatMessage(value: unknown): value is StoredChatMessage {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record.id === "string" &&
    (record.role === "user" || record.role === "assistant") &&
    typeof record.content === "string" &&
    (record.displayOnly === undefined || typeof record.displayOnly === "boolean")
  );
}

/**
 * Load persisted runtime selections, or ``null`` when absent/invalid.
 */
export function loadRuntimeSettings(): StoredRuntimeSettings | null {
  try {
    const raw = localStorage.getItem(RUNTIME_SETTINGS_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    return isStoredRuntimeSettings(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Persist minimal runtime selections for later ask turns (#235).
 */
export function saveRuntimeSettings(value: StoredRuntimeSettings): void {
  try {
    localStorage.setItem(RUNTIME_SETTINGS_STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Quota / private mode — ignore; in-memory UI state still works.
  }
}

/**
 * Load the chat transcript, or ``[]`` when absent/invalid (never throws).
 */
export function loadChatMessages(): StoredChatMessage[] {
  try {
    const raw = localStorage.getItem(CHAT_MESSAGES_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.every(isStoredChatMessage) ? parsed : [];
  } catch {
    return [];
  }
}

/**
 * Persist the chat transcript for the next visit.
 */
export function saveChatMessages(messages: StoredChatMessage[]): void {
  try {
    localStorage.setItem(CHAT_MESSAGES_STORAGE_KEY, JSON.stringify(messages));
  } catch {
    // Quota / private mode — ignore.
  }
}

/**
 * Clear the persisted chat transcript (New chat). Leaves runtime settings alone.
 */
export function clearChatMessages(): void {
  try {
    localStorage.removeItem(CHAT_MESSAGES_STORAGE_KEY);
  } catch {
    // ignore
  }
}
