"""Chat-time intent selection for Software Delivery workflows.

Scaffolding risk/generate/markdown-export matchers stay retired (#285).
#309 restores matching only for Google Drive export requests so the agent
prepared-call path can run when ``SOFTWARE_DELIVERY_AGENT_LOOP`` is on.
"""

from __future__ import annotations

import re

from dataclasses import dataclass

from packs.software_delivery.contracts import (
    TEST_CASE_STYLES,
    TEST_CASE_STYLES_DISPLAY,
    TestCaseStyle,
)
from packs.software_delivery.errors import OrchestrationValidationError

_EXPORT_DRIVE = re.compile(
    r"\bexport\b.*\b(?:google\s+)?drive\b|\b(?:google\s+)?drive\b.*\bexport\b",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class ChatToolSelection:
    """The workflow a chat query asked for.

    Attributes:
        generate_tests (bool): Legacy flag; export intent sets this ``True`` so
            existing ``ToolAugmentedAsk`` / runner wiring stays stable.
        output_style (TestCaseStyle): Unused for Drive export; kept for protocol.
    """

    generate_tests: bool
    output_style: TestCaseStyle

    def __post_init__(self) -> None:
        if not isinstance(self.generate_tests, bool):
            raise OrchestrationValidationError(
                "generate_tests must be a bool, "
                f"got {type(self.generate_tests).__name__}"
            )
        if not isinstance(self.output_style, str):
            raise OrchestrationValidationError(
                f"output_style must be one of {TEST_CASE_STYLES_DISPLAY}, "
                f"got {type(self.output_style).__name__}"
            )
        if self.output_style not in TEST_CASE_STYLES:
            raise OrchestrationValidationError(
                f"output_style must be one of {TEST_CASE_STYLES_DISPLAY}"
            )


def select_chat_intent(query: str) -> ChatToolSelection | None:
    """Match Google Drive export requests; otherwise stay on grounded RAG.

    Args:
        query (str): The user's chat message.

    Returns:
        ChatToolSelection | None: Export selection, or ``None`` for RAG.
    """
    if not isinstance(query, str) or not query.strip():
        return None
    if _EXPORT_DRIVE.search(query) is None:
        return None
    return ChatToolSelection(generate_tests=True, output_style="steps")
