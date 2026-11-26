/**
 * Client-local runtime selections for Settings (#237) and Chat (#235).
 *
 * Keys are shared contracts — do not rename without coordinating both UIs.
 * Ollama base URL is server-owned (`GET /api/v1/settings`); Chat should read it
 * from the catalog, not from this store.
 *
 * Active conversation pointer is owned by #246 under
 * `kernector:active-session:v1` (`web/lib/session/active-session.ts`).
 * Transcripts live in `kernector:conversations:v1`. This module must not
 * clear or rewrite those keys (or the legacy transcript key below) when
 * saving settings.
 */

export const RUNTIME_SETTINGS_STORAGE_KEY = "kernector:runtime-settings:v1";

/**
 * Signed-in generation knobs only (#182). Independent of the anonymous
 * provider/model pair in ``RUNTIME_SETTINGS_STORAGE_KEY``. Scoped per user.
 */
export const GENERATION_SETTINGS_STORAGE_KEY_PREFIX =
  "kernector:generation-settings:v1";

/** Per-account generation settings key (#182 personalisation). */
export function generationSettingsStorageKey(userId: string): string {
  return `${GENERATION_SETTINGS_STORAGE_KEY_PREFIX}:${userId}`;
}

/**
 * Legacy single-transcript key from #235. Read once by
 * `migrateLegacyTranscripts()` (#246) into `kernector:conversations:v1` —
 * do not rename without a migration. Do not write this key from new code.
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
  action?: unknown;
  pendingApproval?: unknown;
  approvalResolution?: unknown;
  feedbackRating?: unknown;
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

function isSettingsMap(value: unknown): value is Record<string, number> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  return Object.values(value as Record<string, unknown>).every(
    (entry) => typeof entry === "number" && Number.isFinite(entry),
  );
}

/** Load signed-in generation knobs, or ``null`` when absent/invalid. */
export function loadGenerationSettings(
  userId: string,
): Record<string, number> | null {
  try {
    const raw = localStorage.getItem(generationSettingsStorageKey(userId));
    if (!raw) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    return isSettingsMap(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** Persist signed-in generation knobs without touching anonymous provider/model. */
export function saveGenerationSettings(
  userId: string,
  settings: Record<string, number>,
): void {
  try {
    localStorage.setItem(
      generationSettingsStorageKey(userId),
      JSON.stringify(settings),
    );
  } catch {
    // Quota / private mode — ignore.
  }
}
