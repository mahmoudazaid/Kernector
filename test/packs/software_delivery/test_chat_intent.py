"""Chat-time intent selection: which tool chain a chat query is asking for."""

from __future__ import annotations

import pytest

from packs.software_delivery.chat_intent import ChatToolSelection, select_chat_intent
from packs.software_delivery.errors import OrchestrationValidationError


def test_a_test_case_request_selects_the_generate_chain() -> None:
    """AC1: 'Create test cases for AUTH-101' must reach the generate chain."""
    assert select_chat_intent("Create test cases for AUTH-101") == ChatToolSelection(
        generate_tests=True, output_style="steps"
    )


@pytest.mark.parametrize(
    "query",
    [
        "Write gherkin test cases for AUTH-101",
        "Generate tests for AUTH-101 in Given/When/Then form",
        "I need a feature file for the login story",
        "Produce cucumber test scenarios for AUTH-101",
    ],
)
def test_gherkin_wording_selects_the_gherkin_style(query: str) -> None:
    selection = select_chat_intent(query)

    assert selection is not None
    assert selection.output_style == "gherkin"


@pytest.mark.parametrize(
    "query",
    [
        "What is the risk score for AUTH-101?",
        "Give me a risk assessment of the MFA rollout",
        "How risky is shipping AUTH-101 this sprint?",
    ],
)
def test_a_risk_question_selects_the_risk_only_chain(query: str) -> None:
    assert select_chat_intent(query) == ChatToolSelection(
        generate_tests=False, output_style="steps"
    )


def test_a_gherkin_test_request_generates_tests_in_gherkin() -> None:
    """Both signals in one query: the chain wins on tests, the style on gherkin."""
    assert select_chat_intent(
        "Score the risk and write gherkin test cases for AUTH-101"
    ) == ChatToolSelection(generate_tests=True, output_style="gherkin")


@pytest.mark.parametrize(
    "query",
    [
        "What is the session timeout?",
        "Summarise the auth docs",
        "Who owns AUTH-101?",
        "Explain how MFA enrolment works",
        "",
        "   ",
    ],
)
def test_a_general_question_selects_no_tool(query: str) -> None:
    """AC3: an ordinary question must not trigger a tool call."""
    assert select_chat_intent(query) is None


def test_an_unknown_style_cannot_be_constructed() -> None:
    with pytest.raises(OrchestrationValidationError, match="output_style"):
        ChatToolSelection(generate_tests=True, output_style="prose")  # type: ignore[arg-type]


def test_registration_exposes_the_chat_intent_selector() -> None:
    """Composition reaches the pack through registration.py and nothing else."""
    from packs.software_delivery.registration import build_chat_intent_selector

    select = build_chat_intent_selector()

    assert select("Create test cases for AUTH-101") == ChatToolSelection(
        generate_tests=True, output_style="steps"
    )
    assert select("What is the session timeout?") is None
