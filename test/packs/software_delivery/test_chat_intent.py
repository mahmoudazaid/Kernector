"""Chat-time intent selection: Drive export only (#309)."""

from __future__ import annotations

import pytest

from packs.software_delivery.chat_intent import ChatToolSelection, select_chat_intent
from packs.software_delivery.errors import OrchestrationValidationError


@pytest.mark.parametrize(
    "query",
    [
        "Create test cases for AUTH-101",
        "Generate tests for AUTH-101",
        "What is the risk score for AUTH-101?",
        "Assess the risk for the MFA rollout",
        "Analyze these requirements:\nAs a user I want MFA.",
        "How do I create test cases?",
        "",
        "   ",
    ],
)
def test_retired_and_non_export_queries_stay_on_rag(query: str) -> None:
    assert select_chat_intent(query) is None


@pytest.mark.parametrize(
    "query",
    [
        "Export selected tests to Google Drive",
        "Please export to google drive",
        "export the test cases to Drive",
        "Can you Drive export the selected titles?",
    ],
)
def test_drive_export_queries_match(query: str) -> None:
    selection = select_chat_intent(query)
    assert selection == ChatToolSelection(generate_tests=True, output_style="steps")


def test_an_unknown_style_cannot_be_constructed() -> None:
    with pytest.raises(OrchestrationValidationError, match="output_style"):
        ChatToolSelection(generate_tests=True, output_style="prose")  # type: ignore[arg-type]


def test_registration_exposes_the_chat_intent_selector() -> None:
    from packs.software_delivery.registration import build_chat_intent_selector

    disabled = build_chat_intent_selector(export_intent_enabled=False)
    assert disabled("Export to Google Drive") is None

    select = build_chat_intent_selector(export_intent_enabled=True)
    assert select("Export to Google Drive") is not None
    assert select("Create test cases for AUTH-101") is None
