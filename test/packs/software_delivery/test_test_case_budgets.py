"""Budget and settings tests for test-case generation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from domain.errors import ToolFailureError
from domain.knowledge import SourceReference
from domain.models import AskResult, Message
from packs.software_delivery.contracts import TestCaseEvidence, TestGenerationRequest
from packs.software_delivery.errors import TestCaseGenerationValidationError
from packs.software_delivery.limits import (
    MAX_SOURCE_ID_CHARS,
    MAX_SOURCE_TYPE_CHARS,
    MAX_TOTAL_INPUT_CHARS,
    TEST_GENERATION_MODEL_SETTINGS,
)
from packs.software_delivery.test_case_generation import generate_test_cases
from packs.software_delivery.test_case_prompt import build_test_case_prompt


class _RecordingChat:
    def __init__(self) -> None:
        self.called = False
        self.settings: Mapping[str, object] | None = None

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        self.called = True
        self.settings = settings
        raise AssertionError("model must not be called for this test")


def test_overlong_source_id_fails_before_prompt() -> None:
    with pytest.raises(TestCaseGenerationValidationError, match="source_id"):
        TestCaseEvidence(
            SourceReference("x" * (MAX_SOURCE_ID_CHARS + 1), "user_story"),
            "body",
        )


def test_overlong_source_type_fails_before_prompt() -> None:
    with pytest.raises(TestCaseGenerationValidationError, match="source_type"):
        TestCaseEvidence(
            SourceReference("US-1", "x" * (MAX_SOURCE_TYPE_CHARS + 1)),
            "body",
        )


def test_serialized_prompt_over_budget_fails_before_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "packs.software_delivery.test_case_prompt.MAX_TOTAL_INPUT_CHARS",
        200,
    )
    request = TestGenerationRequest(
        "Assess a reasonably long authentication target for MFA coverage",
        [
            TestCaseEvidence(
                SourceReference("US-1", "user_story"),
                "Evidence text that expands the serialized untrusted assessment payload.",
            )
        ],
    )
    chat = _RecordingChat()
    with pytest.raises(TestCaseGenerationValidationError, match="serialized prompt"):
        generate_test_cases(request, chat)
    assert chat.called is False
    # Direct prompt builder also rejects
    with pytest.raises(TestCaseGenerationValidationError, match="serialized prompt"):
        build_test_case_prompt(request)


def test_model_settings_constant_is_deterministic_and_bounded() -> None:
    assert TEST_GENERATION_MODEL_SETTINGS == {
        "temperature": 0,
        "max_tokens": 2048,
    }
    assert MAX_TOTAL_INPUT_CHARS == 16_000
