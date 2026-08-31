"""Tests for ChatModel-backed test-case generation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest

from domain.errors import ProviderError, ToolFailureError
from domain.knowledge import SourceReference
from domain.models import AskResult, Message
from packs.software_delivery.contracts import TestCaseEvidence, TestGenerationRequest
from packs.software_delivery.errors import TestCaseGenerationValidationError
from packs.software_delivery.limits import (
    MAX_MODEL_RESPONSE_CHARS,
    MAX_TOTAL_OUTPUT_CHARS,
    TEST_GENERATION_MODEL_SETTINGS,
)
from packs.software_delivery.test_case_generation import generate_test_cases


class _FakeChat:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, Sequence[Message], Mapping[str, object]]] = []

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        self.calls.append((system, messages, settings))
        return AskResult(content=self.content)


def _request(
    style: str = "steps",
    *,
    evidence: list[TestCaseEvidence] | None = None,
) -> TestGenerationRequest:
    items = evidence or [
        TestCaseEvidence(SourceReference("US-1", "user_story"), "Need MFA."),
        TestCaseEvidence(SourceReference("SRS-2", "srs"), "MFA required after password."),
    ]
    return TestGenerationRequest("Assess MFA", items, style)  # type: ignore[arg-type]


def _steps_payload(*, evidence_ids: list[str] | None = None) -> str:
    return json.dumps(
        {
            "test_cases": [
                {
                    "title": "MFA success",
                    "steps": ["Open login", "Enter MFA"],
                    "expected": "Home shown",
                    "evidence_ids": evidence_ids or ["e0"],
                }
            ]
        }
    )


def _gherkin_payload() -> str:
    return json.dumps(
        {
            "test_cases": [
                {
                    "title": "MFA success",
                    "steps": [
                        "Given the user is on login",
                        "When MFA is submitted",
                        "Then the home page is shown",
                    ],
                    "evidence_ids": ["e0", "e1"],
                }
            ]
        }
    )


def test_steps_generation_maps_evidence_ids_and_passes_settings() -> None:
    chat = _FakeChat(_steps_payload(evidence_ids=["e1"]))
    result = generate_test_cases(_request("steps"), chat)
    assert result.output_style == "steps"
    assert result.test_cases[0].references == (
        SourceReference("SRS-2", "srs"),
    )
    assert chat.calls[0][2] == dict(TEST_GENERATION_MODEL_SETTINGS)


def test_gherkin_derives_expected_and_collapses_duplicate_refs() -> None:
    payload = {
        "test_cases": [
            {
                "title": "Dup refs",
                "steps": [
                    "Given a",
                    "When b",
                    "Then first outcome",
                    "And second outcome",
                ],
                "evidence_ids": ["e0", "e0", "e1"],
            }
        ]
    }
    chat = _FakeChat(json.dumps(payload))
    result = generate_test_cases(_request("gherkin"), chat)
    case = result.test_cases[0]
    assert case.expected == "first outcome\nsecond outcome"
    assert case.references == (
        SourceReference("SRS-2", "srs"),
        SourceReference("US-1", "user_story"),
    )
    assert result.output_style == "gherkin"


def test_case_order_preserved() -> None:
    payload = {
        "test_cases": [
            {
                "title": "Second",
                "steps": ["s"],
                "expected": "e",
                "evidence_ids": ["e0"],
            },
            {
                "title": "First",
                "steps": ["s"],
                "expected": "e",
                "evidence_ids": ["e0"],
            },
        ]
    }
    # swap names intentionally — first in JSON is "Second"
    result = generate_test_cases(_request(), _FakeChat(json.dumps(payload)))
    assert [c.title for c in result.test_cases] == ["Second", "First"]


def test_unknown_evidence_id_is_tool_failure() -> None:
    chat = _FakeChat(_steps_payload(evidence_ids=["e99"]))
    with pytest.raises(ToolFailureError, match="unknown evidence_id"):
        generate_test_cases(_request(), chat)


def test_model_supplied_output_style_is_tool_failure() -> None:
    payload = json.loads(_steps_payload())
    payload["output_style"] = "gherkin"
    with pytest.raises(ToolFailureError, match="output_style"):
        generate_test_cases(_request(), _FakeChat(json.dumps(payload)))


def test_gherkin_model_expected_is_tool_failure() -> None:
    payload = json.loads(_gherkin_payload())
    payload["test_cases"][0]["expected"] = "nope"
    with pytest.raises(ToolFailureError, match="expected"):
        generate_test_cases(_request("gherkin"), _FakeChat(json.dumps(payload)))


def test_fabricated_references_are_tool_failure() -> None:
    payload = json.loads(_steps_payload())
    payload["test_cases"][0]["references"] = [
        {"source_id": "evil", "source_type": "srs"}
    ]
    with pytest.raises(ToolFailureError, match="unexpected"):
        generate_test_cases(_request(), _FakeChat(json.dumps(payload)))


def test_provider_error_maps_to_tool_failure_with_cause() -> None:
    class _Boom(_FakeChat):
        def complete(self, system, messages, settings):  # type: ignore[no-untyped-def]
            raise ProviderError("vendor")

    with pytest.raises(ToolFailureError) as captured:
        generate_test_cases(_request(), _Boom(""))
    assert isinstance(captured.value.__cause__, ProviderError)


def test_oversized_raw_response_is_tool_failure() -> None:
    chat = _FakeChat("x" * (MAX_MODEL_RESPONSE_CHARS + 1))
    with pytest.raises(ToolFailureError, match="model response"):
        generate_test_cases(_request(), chat)


def test_over_budget_serialized_result_is_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "packs.software_delivery.test_case_generation.MAX_TOTAL_OUTPUT_CHARS",
        50,
    )
    with pytest.raises(ToolFailureError, match="serialized result"):
        generate_test_cases(_request(), _FakeChat(_steps_payload()))


def test_invalid_model_output_is_not_caller_validation() -> None:
    with pytest.raises(ToolFailureError):
        generate_test_cases(_request(), _FakeChat("not-json"))
    # Ensure it is not the caller validation type
    try:
        generate_test_cases(_request(), _FakeChat("{}"))
    except TestCaseGenerationValidationError:
        pytest.fail("model output must not raise TestCaseGenerationValidationError")
    except ToolFailureError:
        pass
