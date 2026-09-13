"""Chat-time intent selection for Software Delivery workflows.

Retired (#285, choice A): scaffolding risk/generate/export tools no longer
match. ``select_chat_intent`` always returns ``None`` so chat stays on the
grounded-RAG path. ``ChatToolSelection`` remains for registration typing and
``ToolAugmentedAsk``'s ``SelectToolIntent`` protocol until a real tool lands.
"""

from __future__ import annotations

from dataclasses import dataclass

from packs.software_delivery.contracts import (
    TEST_CASE_STYLES,
    TEST_CASE_STYLES_DISPLAY,
    TestCaseStyle,
)
from packs.software_delivery.errors import OrchestrationValidationError


@dataclass(frozen=True, slots=True)
class ChatToolSelection:
    """The workflow a chat query asked for.

    Attributes:
        generate_tests (bool): Whether the chain generates and exports cases.
        output_style (TestCaseStyle): Style for generated cases.
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
    """Return ``None`` so every query stays on grounded RAG.

    Former risk/generate matchers are retired with the scaffolding tools.
    ``query`` is accepted for signature stability with registration and
    ``ToolAugmentedAsk``.

    Args:
        query (str): The user's chat message (unused while intent is retired).

    Returns:
        None: Always; leaves the query on the ordinary grounded-RAG path.
    """
    _ = query
    return None
