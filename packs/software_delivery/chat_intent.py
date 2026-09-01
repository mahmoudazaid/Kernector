"""Deterministic chat-time intent selection for Software Delivery workflows.

A policy, not a classifier. Substring matching over a narrow, pack-authored
vocabulary keeps chat-time tool selection reproducible and testable offline —
the property the prompt-only alternative cannot offer. Narrow is the safe
direction: an unmatched query simply stays on the grounded-RAG path, while a
false match would run tools nobody asked for.
"""

from __future__ import annotations

from dataclasses import dataclass

from packs.software_delivery.contracts import TEST_CASE_STYLES, TestCaseStyle
from packs.software_delivery.errors import OrchestrationValidationError

_TEST_GENERATION_TERMS: tuple[str, ...] = (
    "test case",
    "test cases",
    "test scenario",
    "test scenarios",
    "generate tests",
    "write tests",
    "test plan",
    "acceptance test",
)

_RISK_TERMS: tuple[str, ...] = (
    "risk score",
    "score the risk",
    "risk assessment",
    "assess the risk",
    "how risky",
    "delivery risk",
)

_GHERKIN_TERMS: tuple[str, ...] = (
    "gherkin",
    "given/when/then",
    "given when then",
    "feature file",
    "cucumber",
)


@dataclass(frozen=True, slots=True)
class ChatToolSelection:
    """The tool chain a chat query asked for.

    Attributes:
        generate_tests (bool): Whether the chain generates and exports cases.
        output_style (TestCaseStyle): Style for generated cases.
    """

    generate_tests: bool
    output_style: TestCaseStyle

    def __post_init__(self) -> None:
        if not isinstance(self.generate_tests, bool):
            raise OrchestrationValidationError(
                f"generate_tests must be a bool, got {self.generate_tests!r}"
            )
        if (
            not isinstance(self.output_style, str)
            or self.output_style not in TEST_CASE_STYLES
        ):
            raise OrchestrationValidationError(
                f"output_style must be one of {sorted(TEST_CASE_STYLES)}, "
                f"got {self.output_style!r}"
            )


def select_chat_intent(query: str) -> ChatToolSelection | None:
    """Return the tool chain ``query`` asks for, or ``None`` for grounded chat.

    Args:
        query (str): The user's chat message, unmodified.

    Returns:
        ChatToolSelection | None: ``None`` when no Software Delivery workflow is
            named, which leaves the query on the ordinary grounded-RAG path.
    """
    text = " ".join(query.lower().split())
    gherkin = any(term in text for term in _GHERKIN_TERMS)
    style: TestCaseStyle = "gherkin" if gherkin else "steps"
    # A gherkin term names a test artifact, so it asks for generation on its
    # own: "give me a feature file for the login story" needs no second signal.
    if gherkin or any(term in text for term in _TEST_GENERATION_TERMS):
        return ChatToolSelection(generate_tests=True, output_style=style)
    if any(term in text for term in _RISK_TERMS):
        return ChatToolSelection(generate_tests=False, output_style=style)
    return None
