/**
 * Shape validators for chat message projections (API + persisted transcript).
 *
 * Repair known rendered fields; preserve unknown keys so backend additions
 * are not silently dropped between the API and the UI.
 */

import type { StoredChatMessage } from "@/lib/settings/runtime-settings-storage";

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
  // Preserve unknown keys (usage, warnings, …); only repair `tools`.
  if (run.tools !== undefined && !isStringArray(run.tools)) {
    delete run.tools;
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
  const toolRun: Record<string, unknown> = { ...value };

  delete toolRun.summary;
  if (typeof value.summary === "string") {
    toolRun.summary = value.summary;
  }

  delete toolRun.markdown;
  if (typeof value.markdown === "string") {
    toolRun.markdown = value.markdown;
  }

  delete toolRun.calls;
  if (Array.isArray(value.calls)) {
    toolRun.calls = value.calls.flatMap((entry) => {
      if (
        !isPlainObject(entry) ||
        typeof entry.tool_name !== "string" ||
        typeof entry.ok !== "boolean"
      ) {
        return [];
      }
      if (entry.summary !== undefined && typeof entry.summary !== "string") {
        return [{ tool_name: entry.tool_name, ok: entry.ok }];
      }
      return [entry];
    });
  }

  delete toolRun.risk;
  if (isPlainObject(value.risk)) {
    const risk: Record<string, unknown> = { ...value.risk };
    delete risk.score;
    if (typeof value.risk.score === "number") {
      risk.score = value.risk.score;
    }
    delete risk.level;
    if (typeof value.risk.level === "string") {
      risk.level = value.risk.level;
    }
    delete risk.rationale;
    if (typeof value.risk.rationale === "string") {
      risk.rationale = value.risk.rationale;
    }
    delete risk.factors;
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

  delete toolRun.test_cases;
  if (isPlainObject(value.test_cases)) {
    const testCases: Record<string, unknown> = { ...value.test_cases };
    delete testCases.output_style;
    if (typeof value.test_cases.output_style === "string") {
      testCases.output_style = value.test_cases.output_style;
    }
    delete testCases.cases;
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
