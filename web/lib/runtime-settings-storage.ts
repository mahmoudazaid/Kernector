/**
 * Client-local runtime selections for Settings (#237) and Chat (#235).
 *
 * Keys are shared contracts — do not rename without coordinating both UIs.
 * Ollama base URL is server-owned (`GET /api/v1/settings`); Chat should read it
 * from the catalog, not from this store.
 */

export const RUNTIME_SETTINGS_STORAGE_KEY = "kernector:runtime-settings:v1";

export type StoredRuntimeSettings = {
  provider: string;
  model: string;
  settings: Record<string, number>;
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
