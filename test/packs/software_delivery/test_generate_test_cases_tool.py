"""Tests for software_delivery.generate_test_cases tool adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest

from domain.errors import ToolFailureError
from domain.models import AskResult, Message
from packs.software_delivery.contracts import TestGenerationRequest, TestGenerationResult
from packs.software_delivery.errors import TestCaseGenerationValidationError
from packs.software_delivery.generate_test_cases_tool import (
    TOOL_NAME,
    GenerateTestCasesTool,
)


class _FakeChat:
    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        self.calls += 1
        return AskResult(
            content=json.dumps(
                {
                    "test_cases": [
                        {
                            "title": "MFA",
                            "steps": ["Open", "Submit"],
                            "expected": "OK",
                            "evidence_ids": ["e0"],
                        }
                    ]
                }
            )
        )


def _valid_arguments(**overrides: object) -> dict[str, object]:
    args: dict[str, object] = {
        "target": "Assess authentication release risk",
        "evidence": [
            {
                "source_id": "US-12",
                "source_type": "user_story",
                "text": "As a user I want MFA.",
            }
        ],
    }
    args.update(overrides)
    return args


def test_tool_name_and_description() -> None:
    tool = GenerateTestCasesTool(_FakeChat())
    assert tool.name == TOOL_NAME == "software_delivery.generate_test_cases"
    assert tool.description.strip()


def test_omitted_style_defaults_to_steps() -> None:
    chat = _FakeChat()
    payload = json.loads(GenerateTestCasesTool(chat).run(_valid_arguments()))
    assert payload["output_style"] == "steps"
    assert payload["test_cases"][0]["title"] == "MFA"
    assert payload["test_cases"][0]["references"] == [
        {"source_id": "US-12", "source_type": "user_story"}
    ]
    assert chat.calls == 1


def test_explicit_gherkin_style_round_trip() -> None:
    class _GherkinChat(_FakeChat):
        def complete(self, system, messages, settings):  # type: ignore[no-untyped-def]
            self.calls += 1
            return AskResult(
                content=json.dumps(
                    {
                        "test_cases": [
                            {
                                "title": "MFA",
                                "steps": [
                                    "Given login page",
                                    "When MFA entered",
                                    "Then home shown",
                                ],
                                "evidence_ids": ["e0"],
                            }
                        ]
                    }
                )
            )

    payload = json.loads(
        GenerateTestCasesTool(_GherkinChat()).run(
            _valid_arguments(output_style="gherkin")
        )
    )
    assert payload["output_style"] == "gherkin"
    assert payload["test_cases"][0]["expected"] == "home shown"
    assert "references" in payload["test_cases"][0]


def test_invalid_style_fails_before_model() -> None:
    chat = _FakeChat()
    with pytest.raises(TestCaseGenerationValidationError, match="output_style"):
        GenerateTestCasesTool(chat).run(_valid_arguments(output_style="cucumber"))
    assert chat.calls == 0


def test_unknown_root_key_fails_before_model() -> None:
    chat = _FakeChat()
    args = _valid_arguments()
    args["extra"] = "nope"
    with pytest.raises(TestCaseGenerationValidationError, match="unknown"):
        GenerateTestCasesTool(chat).run(args)
    assert chat.calls == 0


def test_generator_failure_is_not_validation_error() -> None:
    def boom(
        request: TestGenerationRequest, chat_model: object
    ) -> TestGenerationResult:
        raise ToolFailureError("bad model output")

    with pytest.raises(ToolFailureError, match="bad model output"):
        GenerateTestCasesTool(_FakeChat(), generator=boom).run(_valid_arguments())
