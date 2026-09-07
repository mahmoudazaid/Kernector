/**
 * Client-local runtime selections for Settings (#237) and Chat (#235).
 *
 * Keys are shared contracts — do not rename without coordinating both UIs.
 * Ollama base URL is server-owned (`GET /api/v1/settings`); Chat should read it
 * from the catalog, not from this store.
 *
 * Active chat session (draft + transcript) is owned by #14 under
 * `kernector:active-session:v1` (`web/lib/session/active-session.ts`). This
 * module must not clear or rewrite that key (or the legacy transcript key
 * below) when saving settings.
 */

export const RUNTIME_SETTINGS_STORAGE_KEY = "kernector:runtime-settings:v1";

/**
 * Legacy chat transcript key from #235. Owned by the #14 session store as a
 * write-through mirror and absent/unusable-session read fallback — do not
 * rename without a migration. Callers must use `loadActiveSession` /
 * `saveActiveSession` / `clearActiveSession`; do not read or write this key
 * directly.
 */
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

function isStoredRuntimeSettings(
  value: unknown,
): value is StoredRuntimeSettings {
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
