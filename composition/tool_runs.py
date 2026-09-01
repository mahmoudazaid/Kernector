"""Generic tool-call envelope for presentation surfaces.

Carries only what the UI may show safely: tool name, outcome status, and a
bounded summary. Raw opaque tool payloads stay outside this type; #170 maps
``InvokeToolResponse.result`` into typed views before presentation renders.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_TOOL_CALL_SUMMARY_CHARS = 120


@dataclass(frozen=True, slots=True)
class ToolCallView:
    """One tool invocation as presentation sees it.

    Attributes:
        tool_name (str): Registered tool that ran.
        ok (bool): Whether the invocation completed successfully.
        summary (str): Bounded, user-safe description of the outcome. Never the
            full opaque tool payload.
    """

    tool_name: str
    ok: bool
    summary: str = ""

    def __post_init__(self) -> None:
        if len(self.summary) > MAX_TOOL_CALL_SUMMARY_CHARS:
            raise ValueError(
                f"summary must be at most {MAX_TOOL_CALL_SUMMARY_CHARS} "
                f"characters, got {len(self.summary)}"
            )


def bounded_tool_call_summary(
    text: str,
    *,
    limit: int = MAX_TOOL_CALL_SUMMARY_CHARS,
) -> str:
    """Return a user-safe summary truncated to ``limit`` characters."""
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 1].rstrip() + "…"
