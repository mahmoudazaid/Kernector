"""Pure projection of safe RunMeta fields for UI display."""

from __future__ import annotations

from application.contracts import RunMeta


def run_detail_lines(result: RunMeta | None) -> tuple[str, ...]:
    """Project safe execution fields for UI display; omit unset optionals.

    Never includes prompts, queries, chunks, tool payloads, settings blobs, or
    exception type/message text — only the allowlisted labels from the run
    details contract.
    """
    if result is None:
        return ()

    lines: list[str] = []
    if result.request_id:
        lines.append(f"Request ID: {result.request_id}")
    if result.outcome:
        lines.append(f"Outcome: {result.outcome}")
    if result.latency_ms is not None:
        lines.append(f"Latency: {result.latency_ms}ms")
    if result.model:
        lines.append(f"Model: {result.model}")
    usage = result.usage
    if usage is not None:
        if usage.total_tokens is not None:
            lines.append(f"Tokens: {usage.total_tokens}")
        elif usage.prompt_tokens is not None and usage.completion_tokens is not None:
            lines.append(
                f"Tokens: {usage.prompt_tokens} in / {usage.completion_tokens} out"
            )
    if result.pack:
        lines.append(f"Pack: {result.pack}")
    if result.hit_count is not None:
        lines.append(f"Retrieval hits: {result.hit_count}")
    if result.tools:
        lines.append(f"Tools: {', '.join(result.tools)}")
    return tuple(lines)
