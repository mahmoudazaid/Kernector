"""Deterministic chat-time intent selection for Software Delivery workflows.

A policy, not a classifier. Explicit creation or risk-request patterns over a
narrow, pack-authored vocabulary keep chat-time tool selection reproducible and
testable offline. Narrow is the safe direction: an unmatched query simply stays
on the grounded-RAG path, while a false match would run tools nobody asked for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from packs.software_delivery.contracts import TEST_CASE_STYLES, TestCaseStyle
from packs.software_delivery.errors import OrchestrationValidationError

_CREATION = re.compile(r"\b(?:create|generate|write|produce|draft|build)\b")

_TEST_ARTIFACT = re.compile(
    r"\b(?:"
    r"test cases?|test scenarios?|acceptance tests?|test plan|"
    r"feature files?|cucumber scenarios?"
    r"|tests"
    r")\b"
)

_GHERKIN_STYLE = re.compile(
    r"\b(?:gherkin|cucumber|given/when/then|given when then|feature files?)\b"
)

_RISK_REQUEST = re.compile(
    r"(?:"
    r"(?:assess|score|evaluate)\s+(?:the\s+)?(?:delivery\s+)?risk\b"
    r"|what is the risk score for\b"
    r"|how risky is\b"
    r"|(?:give me )?(?:a )?risk assessment of\b"
    r")"
)

_RISK_EXPLANATORY = re.compile(
    r"(?:"
    r"how is (?:a |the )?risk score"
    r"|how are risk scores"
    r"|what is (?:a )?risk score\??$"
    r"|explain (?:the |a )?risk score"
    r"|how (?:is|are) .* risk score .* calculated"
    r")"
)

_NEGATION = re.compile(r"\b(?:do not|dont|never)\b")

_CONCEPTUAL = re.compile(
    r"(?:"
    r"what is gherkin\??"
    r"|how is (?:a |the )?risk score calculated"
    r"|summari[sz]e (?:the )?test plan"
    r"|which test cases\b"
    r")"
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


def _normalize(query: str) -> str:
    """Lowercase, collapse whitespace, and normalize apostrophes for negation."""
    text = query.lower().replace("\u2019", "'")
    text = text.replace("don't", "dont")
    return " ".join(text.split())


def _is_negated(text: str) -> bool:
    """Return whether negation blocks an otherwise explicit tool request."""
    if not _NEGATION.search(text):
        return False
    return bool(
        _CREATION.search(text)
        or _TEST_ARTIFACT.search(text)
        or _GHERKIN_STYLE.search(text)
        or _RISK_REQUEST.search(text)
    )


def select_chat_intent(query: str) -> ChatToolSelection | None:
    """Return the tool chain ``query`` asks for, or ``None`` for grounded chat.

    Test generation requires a creation verb **and** a test artifact — gherkin,
    cucumber, feature file, test plan, or test cases alone are not enough.
    Risk routing accepts explicit score/assessment requests, not explanatory
    questions about how scoring works.

    Args:
        query (str): The user's chat message, unmodified.

    Returns:
        ChatToolSelection | None: ``None`` when no Software Delivery workflow is
            explicitly named, which leaves the query on the ordinary grounded-RAG
            path.
    """
    text = _normalize(query)
    if not text:
        return None
    if _CONCEPTUAL.search(text):
        return None
    if _is_negated(text):
        return None
    if _CREATION.search(text) and _TEST_ARTIFACT.search(text):
        style: TestCaseStyle = "gherkin" if _GHERKIN_STYLE.search(text) else "steps"
        return ChatToolSelection(generate_tests=True, output_style=style)
    if _RISK_EXPLANATORY.search(text):
        return None
    if _RISK_REQUEST.search(text):
        return ChatToolSelection(generate_tests=False, output_style="steps")
    return None
