"""Chat-time intent selection: retired scaffolding tools never match."""

from __future__ import annotations

import pytest

from packs.software_delivery.chat_intent import ChatToolSelection, select_chat_intent
from packs.software_delivery.errors import OrchestrationValidationError


@pytest.mark.parametrize(
    "query",
    [
        # Former generation matches
        "Create test cases for AUTH-101",
        "Generate tests for AUTH-101",
        "Generate comprehensive tests for AUTH-101",
        "Draft a test plan for AUTH-101",
        "Write gherkin test cases for AUTH-101",
        "Generate tests for AUTH-101 in Given/When/Then form",
        "Write a Gherkin feature file",
        "Write a feature file for the login story",
        "Produce Cucumber scenarios",
        "Produce cucumber test scenarios for AUTH-101",
        "Score the risk and write gherkin test cases for AUTH-101",
        "Create test cases that do not require admin access",
        "Create tests; never use production credentials",
        "Do not summarize the docs; create test cases for AUTH-101",
        "Assess the risk and create test cases for AUTH-101",
        # Former risk-only matches
        "What is the risk score for AUTH-101?",
        "Give me a risk assessment of the MFA rollout",
        "How risky is shipping AUTH-101 this sprint?",
        "Assess the risk for the MFA rollout",
        "Score the delivery risk for AUTH-101",
        "Evaluate the risk before we ship",
        "Do not generate tests; assess the risk for AUTH-101",
        "Do not analyze these requirements; assess the risk for AUTH-101",
        # Analysis / non-tool (already None; keep as regression)
        "Analyze these requirements:\nAs a user I want MFA.",
        "Review this story: Login must lock after five failures.",
        "Analyze requirements for AUTH-101",
        "Do not generate tests; analyze these requirements: Need MFA.",
        "Create a summary of existing test cases",
        "How do I create test cases?",
        "What is a risk score?",
        "What is the session timeout?",
        "",
        "   ",
    ],
)
def test_select_chat_intent_always_returns_none(query: str) -> None:
    """Choice A (#285): former tool-shaped queries stay on grounded RAG."""
    assert select_chat_intent(query) is None


def test_an_unknown_style_cannot_be_constructed() -> None:
    with pytest.raises(OrchestrationValidationError, match="output_style"):
        ChatToolSelection(generate_tests=True, output_style="prose")  # type: ignore[arg-type]


def test_registration_exposes_the_chat_intent_selector() -> None:
    """Composition reaches the pack through registration.py and nothing else."""
    from packs.software_delivery.registration import build_chat_intent_selector

    select = build_chat_intent_selector()

    assert select("Create test cases for AUTH-101") is None
    assert select("Do not generate tests; assess the risk for AUTH-101") is None
    assert select("What is the session timeout?") is None
