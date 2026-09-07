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

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === "string");
}

/** Citations: non-null objects with primitive-ish provenance fields. */
function sanitizeCitations(value: unknown): unknown[] | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (!Array.isArray(value)) {
    return undefined;
  }
  const rows = value.flatMap((entry) => {
    if (!isPlainObject(entry) || typeof entry.source_id !== "string") {
      return [];
    }
    if (
      entry.source_type !== undefined &&
      typeof entry.source_type !== "string"
    ) {
      return [];
    }
    if (
      entry.quote !== undefined &&
      entry.quote !== null &&
      typeof entry.quote !== "string"
    ) {
      return [];
    }
    if (
      entry.chunk_index !== undefined &&
      entry.chunk_index !== null &&
      typeof entry.chunk_index !== "number"
    ) {
      return [];
    }
    return [entry];
  });
  return rows;
}

function sanitizeToolsUsed(value: unknown): unknown[] | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (!Array.isArray(value)) {
    return undefined;
  }
  const rows = value.flatMap((entry) => {
    if (
      !isPlainObject(entry) ||
      typeof entry.tool_name !== "string" ||
      typeof entry.result_chars !== "number"
    ) {
      return [];
    }
    return [entry];
  });
  return rows;
}

function sanitizeRun(value: unknown): Record<string, unknown> | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (!isPlainObject(value)) {
    return undefined;
  }
  const run: Record<string, unknown> = { ...value };
  if (run.tools !== undefined && !isStringArray(run.tools)) {
    delete run.tools;
  }
  for (const [key, entry] of Object.entries(run)) {
    if (key === "tools") {
      continue;
    }
    if (
      entry !== null &&
      typeof entry === "object"
    ) {
      // Nested objects (other than tools[]) are not rendered as text leaves.
      delete run[key];
    }
  }
  return run;
}

function sanitizeToolRun(
  value: unknown,
): Record<string, unknown> | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (!isPlainObject(value)) {
    return undefined;
  }
  const toolRun: Record<string, unknown> = {};
  if (typeof value.summary === "string") {
    toolRun.summary = value.summary;
  }
  if (typeof value.markdown === "string") {
    toolRun.markdown = value.markdown;
  }
  if (Array.isArray(value.calls)) {
    toolRun.calls = value.calls.flatMap((entry) => {
      if (
        !isPlainObject(entry) ||
        typeof entry.tool_name !== "string" ||
        typeof entry.ok !== "boolean"
      ) {
        return [];
      }
      if (
        entry.summary !== undefined &&
        typeof entry.summary !== "string"
      ) {
        return [{ tool_name: entry.tool_name, ok: entry.ok }];
      }
      return [entry];
    });
  }
  if (isPlainObject(value.risk)) {
    const risk: Record<string, unknown> = {};
    if (typeof value.risk.score === "number") {
      risk.score = value.risk.score;
    }
    if (typeof value.risk.level === "string") {
      risk.level = value.risk.level;
    }
    if (typeof value.risk.rationale === "string") {
      risk.rationale = value.risk.rationale;
    }
    if (Array.isArray(value.risk.factors)) {
      risk.factors = value.risk.factors.flatMap((entry) => {
        if (
          !isPlainObject(entry) ||
          typeof entry.factor_id !== "string" ||
          typeof entry.weight !== "number"
        ) {
          return [];
        }
        return [entry];
      });
    }
    toolRun.risk = risk;
  }
  if (isPlainObject(value.test_cases)) {
    const testCases: Record<string, unknown> = {};
    if (typeof value.test_cases.output_style === "string") {
      testCases.output_style = value.test_cases.output_style;
    }
    if (Array.isArray(value.test_cases.cases)) {
      testCases.cases = value.test_cases.cases.flatMap((entry) => {
        if (
          !isPlainObject(entry) ||
          typeof entry.title !== "string" ||
          typeof entry.expected !== "string"
        ) {
          return [];
        }
        const steps = isStringArray(entry.steps) ? entry.steps : [];
        return [{ ...entry, steps }];
      });
    }
    toolRun.test_cases = testCases;
  }
  return toolRun;
}

/**
 * Core message shape plus structurally safe optional projections.
 * Invalid projections are dropped so a poisoned leaf cannot blank the panel.
 */
export function sanitizeStoredChatMessage(
  value: unknown,
): StoredChatMessage | null {
  if (!isPlainObject(value)) {
    return null;
  }
  if (
    typeof value.id !== "string" ||
    (value.role !== "user" && value.role !== "assistant") ||
    typeof value.content !== "string"
  ) {
    return null;
  }
  if (
    value.displayOnly !== undefined &&
    typeof value.displayOnly !== "boolean"
  ) {
    return null;
  }

  const message: StoredChatMessage = {
    id: value.id,
    role: value.role,
    content: value.content,
  };
  if (value.displayOnly !== undefined) {
    message.displayOnly = value.displayOnly;
  }

  if ("citations" in value) {
    const citations = sanitizeCitations(value.citations);
    if (citations !== undefined) {
      message.citations = citations;
    }
  }
  if ("toolsUsed" in value) {
    const toolsUsed = sanitizeToolsUsed(value.toolsUsed);
    if (toolsUsed !== undefined) {
      message.toolsUsed = toolsUsed;
    }
  }
  if ("run" in value) {
    const run = sanitizeRun(value.run);
    if (run !== undefined) {
      message.run = run;
    }
  }
  if ("toolRun" in value) {
    const toolRun = sanitizeToolRun(value.toolRun);
    if (toolRun !== undefined) {
      message.toolRun = toolRun;
    }
  }

  return message;
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
 * writes permanently. Refuses when the caller's stamp is older than storage.
 * Dual-writes `messages` to `CHAT_MESSAGES_STORAGE_KEY` as a write-through
 * mirror. Returns the stamp written (or the stored stamp when refused).
 */
export function saveActiveSession(session: ActiveSession): number {
  try {
    const stored = readStoredSession();
    if (stored && stored.updatedAt > session.updatedAt) {
      return stored.updatedAt;
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
 * Returns the stamp written, or the current storage stamp when the write was
 * skipped because a newer revision already owns the transcript.
 */
export function saveActiveSessionDraft(
  draft: string,
  updatedAt: number,
): number {
  try {
    const stored = readStoredSession() ?? emptySession();
    if (stored.updatedAt > updatedAt) {
      return stored.updatedAt;
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
