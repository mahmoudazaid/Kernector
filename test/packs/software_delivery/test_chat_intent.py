"""Chat-time intent selection: which tool chain a chat query is asking for."""

from __future__ import annotations

import pytest

from packs.software_delivery.chat_intent import ChatToolSelection, select_chat_intent
from packs.software_delivery.errors import OrchestrationValidationError


@pytest.mark.parametrize(
    ("query", "style"),
    [
        ("Create test cases for AUTH-101", "steps"),
        ("Generate tests for AUTH-101", "steps"),
        ("Generate comprehensive tests for AUTH-101", "steps"),
        ("Draft a test plan for AUTH-101", "steps"),
        ("Write gherkin test cases for AUTH-101", "gherkin"),
        ("Generate tests for AUTH-101 in Given/When/Then form", "gherkin"),
        ("Write a Gherkin feature file", "gherkin"),
        ("Write a feature file for the login story", "gherkin"),
        ("Produce Cucumber scenarios", "gherkin"),
        ("Produce cucumber test scenarios for AUTH-101", "gherkin"),
        (
            "Score the risk and write gherkin test cases for AUTH-101",
            "gherkin",
        ),
        ("Create test cases that do not require admin access", "steps"),
        ("Create tests; never use production credentials", "steps"),
        ("Do not summarize the docs; create test cases for AUTH-101", "steps"),
    ],
)
def test_explicit_generation_requests_select_the_expected_chain(
    query: str, style: str
) -> None:
    assert select_chat_intent(query) == ChatToolSelection(
        generate_tests=True, output_style=style  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "query",
    [
        "What is the risk score for AUTH-101?",
        "Give me a risk assessment of the MFA rollout",
        "How risky is shipping AUTH-101 this sprint?",
        "Assess the risk for the MFA rollout",
        "Score the delivery risk for AUTH-101",
        "Evaluate the risk before we ship",
        "Do not generate tests; assess the risk for AUTH-101",
    ],
)
def test_an_explicit_risk_request_selects_the_risk_only_chain(query: str) -> None:
    assert select_chat_intent(query) == ChatToolSelection(
        generate_tests=False, output_style="steps"
    )


@pytest.mark.parametrize(
    "query",
    [
        "Create a summary, not test cases",
        "Create a summary of existing test cases",
        "Create a list of test cases",
        "Create an overview of the test plan",
        "Generate a report without creating tests",
        "How do I create test cases?",
        "How to write Gherkin scenarios",
        "Explain how to generate tests",
        "What is Gherkin?",
        "How is a risk score calculated?",
        "Summarise the test plan",
        "Which test cases cover AUTH-101?",
        "I need a feature file for the login story",
        "Show me the test plan for AUTH-101",
        "What is a risk score?",
        "Explain the risk score model",
        "Do not create test cases",
        "Do not generate test cases for AUTH-101",
        "Don't create tests for AUTH-101",
        "Dont write test cases for AUTH-101",
        "Never generate tests",
        "Never generate test scenarios for login",
        "Do not assess the risk",
        "Do not assess the risk for AUTH-101",
        "gherkin",
        "cucumber scenarios",
        "feature file",
        "test plan",
        "test cases for AUTH-101",
        "What is the session timeout?",
        "Summarise the auth docs",
        "Who owns AUTH-101?",
        "Explain how MFA enrolment works",
        "",
        "   ",
    ],
)
def test_non_tool_requests_select_no_tool(query: str) -> None:
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
    assert select("Create a summary of existing test cases") is None
    assert select("What is the session timeout?") is None
    assert select(
        "Do not generate tests; assess the risk for AUTH-101"
    ) == ChatToolSelection(generate_tests=False, output_style="steps")
