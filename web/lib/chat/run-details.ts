import type { RunMeta } from "@/lib/chat/turn";

/**
 * Project safe run fields for UI display (Streamlit ``run_detail_lines`` parity).
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
  if (run.tools && run.tools.length > 0) {
    lines.push(`Tools: ${run.tools.join(", ")}`);
  }
  return lines;
}
