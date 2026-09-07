import type { RunMeta } from "@/lib/chat/turn";

/**
 * Fields that `runDetailLines` interpolates into the UI.
 * `sanitizeRun` repairs these same keys. Lockstep with the projection is
 * enforced by the source-scan test in `chat-sanitize.test.ts`.
 */
export const RUN_STRING_FIELDS = [
  "request_id",
  "outcome",
  "model",
  "pack",
] as const;

export const RUN_NUMBER_FIELDS = [
  "latency_ms",
  "total_tokens",
  "prompt_tokens",
  "completion_tokens",
  "hit_count",
  "citation_count",
] as const;

export const RUN_BOOLEAN_FIELDS = ["query_rewritten"] as const;

export const RUN_STRING_ARRAY_FIELDS = ["tools"] as const;

/** Every run key that can appear in a rendered detail line. */
export const RUN_RENDERED_FIELDS = [
  ...RUN_STRING_FIELDS,
  ...RUN_NUMBER_FIELDS,
  ...RUN_BOOLEAN_FIELDS,
  ...RUN_STRING_ARRAY_FIELDS,
] as const;

/**
 * Project safe run fields from typed `RunMeta` for UI display.
 */
export function runDetailLines(run: RunMeta | null | undefined): string[] {
  if (!run) {
    return [];
  }
  const lines: string[] = [];
  if (run.request_id) {
    lines.push(`Request ID: ${run.request_id}`);
  }
  if (run.outcome) {
    lines.push(`Outcome: ${run.outcome}`);
  }
  if (run.latency_ms != null) {
    lines.push(`Latency: ${run.latency_ms}ms`);
  }
  if (run.model) {
    lines.push(`Model: ${run.model}`);
  }
  if (run.total_tokens != null) {
    lines.push(`Tokens: ${run.total_tokens}`);
  } else if (run.prompt_tokens != null && run.completion_tokens != null) {
    lines.push(`Tokens: ${run.prompt_tokens} in / ${run.completion_tokens} out`);
  }
  if (run.pack) {
    lines.push(`Pack: ${run.pack}`);
  }
  if (run.query_rewritten != null) {
    lines.push(`Query rewritten: ${run.query_rewritten ? "yes" : "no"}`);
  }
  if (run.hit_count != null) {
    lines.push(`Retrieval hits: ${run.hit_count}`);
  }
  if (run.citation_count != null) {
    lines.push(`Citations: ${run.citation_count}`);
  }
  if (Array.isArray(run.tools) && run.tools.length > 0) {
    lines.push(`Tools: ${run.tools.join(", ")}`);
  }
  return lines;
}
