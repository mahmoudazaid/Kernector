"""Generic tool-call envelope for presentation surfaces.

Carries tool name, outcome status, and an explicitly authored summary for
renderers. Not stored on ``AskResponse.tool_outputs`` (opaque
``InvokeToolResponse`` only). ``project_software_delivery_run_view`` builds
these views from validated typed metadata — never from
``InvokeToolResponse.result`` or truncated opaque payloads.
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
        summary (str): Short description authored from typed metadata at the
            composition boundary (for example score or generated-case count).
            At most ``MAX_TOOL_CALL_SUMMARY_CHARS`` characters. Never copied or
            truncated from an opaque tool payload.
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
