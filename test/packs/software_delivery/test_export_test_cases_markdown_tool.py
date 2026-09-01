"""Tests for software_delivery.export_test_cases_markdown tool adapter."""

from __future__ import annotations

import pytest

from domain.errors import ToolFailureError
from packs.software_delivery.contracts import TestGenerationResult
from packs.software_delivery.errors import MarkdownExportValidationError
from packs.software_delivery.export_test_cases_markdown_tool import (
    TOOL_NAME,
    ExportTestCasesMarkdownTool,
)


def _valid_arguments(**overrides: object) -> dict[str, object]:
    args: dict[str, object] = {
        "output_style": "steps",
        "test_cases": [
            {
                "title": "Login with MFA",
                "steps": ["Open login page", "Submit credentials"],
                "expected": "User is authenticated.",
                "references": [
                    {"source_id": "US-12", "source_type": "user_story"},
                ],
            }
        ],
    }
    args.update(overrides)
    return args


def test_tool_name_and_description() -> None:
    tool = ExportTestCasesMarkdownTool()
    assert tool.name == TOOL_NAME == "software_delivery.export_test_cases_markdown"
    assert tool.description.strip()


def test_empty_test_cases_fails_before_formatter() -> None:
    calls: list[TestGenerationResult] = []

    def boom(result: TestGenerationResult) -> str:
        calls.append(result)
        raise AssertionError("formatter must not run")

    with pytest.raises(MarkdownExportValidationError, match="test_cases"):
        ExportTestCasesMarkdownTool(formatter=boom).run(
            _valid_arguments(test_cases=[])
        )
    assert calls == []


def test_unknown_root_key_fails_before_formatter() -> None:
    calls: list[TestGenerationResult] = []

    def boom(result: TestGenerationResult) -> str:
        calls.append(result)
        raise AssertionError("formatter must not run")

    args = _valid_arguments()
    args["extra"] = "nope"
    with pytest.raises(MarkdownExportValidationError, match="unknown"):
        ExportTestCasesMarkdownTool(formatter=boom).run(args)
    assert calls == []


def test_valid_arguments_return_markdown() -> None:
    markdown = ExportTestCasesMarkdownTool().run(_valid_arguments())
    assert "## 1. Login with MFA" in markdown
    assert "1. Open login page" in markdown
    assert "User is authenticated." in markdown
    assert "`US-12` (user_story)" in markdown


def test_formatter_failure_is_not_validation_error() -> None:
    def boom(result: TestGenerationResult) -> str:
        raise ToolFailureError("bad formatter output")

    with pytest.raises(ToolFailureError, match="bad formatter output"):
        ExportTestCasesMarkdownTool(formatter=boom).run(_valid_arguments())
