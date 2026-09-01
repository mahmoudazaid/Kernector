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
from packs.software_delivery.limits import (
    MAX_EVIDENCE_IDS_PER_CASE,
    MAX_EXPECTED_CHARS,
    MAX_GENERATED_CASES,
    MAX_SOURCE_ID_CHARS,
    MAX_SOURCE_TYPE_CHARS,
    MAX_STEP_CHARS,
    MAX_STEPS_PER_CASE,
    MAX_TITLE_CHARS,
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


def _spy_formatter() -> tuple[list[TestGenerationResult], object]:
    calls: list[TestGenerationResult] = []

    def boom(result: TestGenerationResult) -> str:
        calls.append(result)
        raise AssertionError("formatter must not run")

    return calls, boom


def test_tool_name_and_description() -> None:
    tool = ExportTestCasesMarkdownTool()
    assert tool.name == TOOL_NAME == "software_delivery.export_test_cases_markdown"
    assert tool.description.strip()


def test_empty_test_cases_fails_before_formatter() -> None:
    calls, boom = _spy_formatter()
    with pytest.raises(MarkdownExportValidationError, match="test_cases"):
        ExportTestCasesMarkdownTool(formatter=boom).run(
            _valid_arguments(test_cases=[])
        )
    assert calls == []


def test_mixed_type_root_key_fails_before_formatter() -> None:
    calls, boom = _spy_formatter()
    args = _valid_arguments()
    args[1] = "nope"  # type: ignore[index]
    with pytest.raises(MarkdownExportValidationError, match="non-blank strings"):
        ExportTestCasesMarkdownTool(formatter=boom).run(args)
    assert calls == []


def test_unknown_root_key_fails_before_formatter() -> None:
    calls, boom = _spy_formatter()
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


def test_formatter_validation_error_maps_to_tool_failure() -> None:
    def boom(result: TestGenerationResult) -> str:
        raise MarkdownExportValidationError("formatter-side validation")

    with pytest.raises(ToolFailureError, match="Markdown export failed"):
        ExportTestCasesMarkdownTool(formatter=boom).run(_valid_arguments())


def test_formatter_unexpected_error_maps_to_tool_failure() -> None:
    def boom(result: TestGenerationResult) -> str:
        raise RuntimeError("boom")

    with pytest.raises(ToolFailureError, match="Markdown export failed"):
        ExportTestCasesMarkdownTool(formatter=boom).run(_valid_arguments())


@pytest.mark.parametrize(
    ("field", "overrides", "pattern"),
    [
        (
            "test_cases count",
            {
                "test_cases": [
                    {
                        "title": f"Case {index}",
                        "steps": ["Act"],
                        "expected": "OK",
                        "references": [
                            {"source_id": "US-1", "source_type": "user_story"}
                        ],
                    }
                    for index in range(MAX_GENERATED_CASES + 1)
                ]
            },
            "test_cases must have at most",
        ),
        (
            "title length",
            {
                "test_cases": [
                    {
                        "title": "x" * (MAX_TITLE_CHARS + 1),
                        "steps": ["Act"],
                        "expected": "OK",
                        "references": [
                            {"source_id": "US-1", "source_type": "user_story"}
                        ],
                    }
                ]
            },
            "title must be at most",
        ),
        (
            "steps count",
            {
                "test_cases": [
                    {
                        "title": "Case",
                        "steps": ["Act"] * (MAX_STEPS_PER_CASE + 1),
                        "expected": "OK",
                        "references": [
                            {"source_id": "US-1", "source_type": "user_story"}
                        ],
                    }
                ]
            },
            "steps must have at most",
        ),
        (
            "step length",
            {
                "test_cases": [
                    {
                        "title": "Case",
                        "steps": ["x" * (MAX_STEP_CHARS + 1)],
                        "expected": "OK",
                        "references": [
                            {"source_id": "US-1", "source_type": "user_story"}
                        ],
                    }
                ]
            },
            "steps items must be at most",
        ),
        (
            "expected length",
            {
                "test_cases": [
                    {
                        "title": "Case",
                        "steps": ["Act"],
                        "expected": "x" * (MAX_EXPECTED_CHARS + 1),
                        "references": [
                            {"source_id": "US-1", "source_type": "user_story"}
                        ],
                    }
                ]
            },
            "expected must be at most",
        ),
        (
            "references count",
            {
                "test_cases": [
                    {
                        "title": "Case",
                        "steps": ["Act"],
                        "expected": "OK",
                        "references": [
                            {
                                "source_id": f"US-{index}",
                                "source_type": "user_story",
                            }
                            for index in range(MAX_EVIDENCE_IDS_PER_CASE + 1)
                        ],
                    }
                ]
            },
            "references must have at most",
        ),
        (
            "source_id length",
            {
                "test_cases": [
                    {
                        "title": "Case",
                        "steps": ["Act"],
                        "expected": "OK",
                        "references": [
                            {
                                "source_id": "x" * (MAX_SOURCE_ID_CHARS + 1),
                                "source_type": "user_story",
                            }
                        ],
                    }
                ]
            },
            "source_id must be at most",
        ),
        (
            "source_type length",
            {
                "test_cases": [
                    {
                        "title": "Case",
                        "steps": ["Act"],
                        "expected": "OK",
                        "references": [
                            {
                                "source_id": "US-1",
                                "source_type": "x" * (MAX_SOURCE_TYPE_CHARS + 1),
                            }
                        ],
                    }
                ]
            },
            "source_type must be at most",
        ),
    ],
)
def test_limit_boundary_fails_before_formatter(
    field: str,
    overrides: dict[str, object],
    pattern: str,
) -> None:
    calls, boom = _spy_formatter()
    with pytest.raises(MarkdownExportValidationError, match=pattern):
        ExportTestCasesMarkdownTool(formatter=boom).run(_valid_arguments(**overrides))
    assert calls == []


def test_cumulative_result_budget_fails_before_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "packs.software_delivery.test_case_generation.MAX_TOTAL_OUTPUT_CHARS",
        120,
    )
    calls, boom = _spy_formatter()
    with pytest.raises(MarkdownExportValidationError, match="serialized result"):
        ExportTestCasesMarkdownTool(formatter=boom).run(_valid_arguments())
    assert calls == []
