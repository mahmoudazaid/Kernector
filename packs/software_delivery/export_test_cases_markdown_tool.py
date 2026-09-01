"""Tool adapter for ``software_delivery.export_test_cases_markdown``."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from domain.errors import DomainValidationError, ToolFailureError
from domain.knowledge import SourceReference
from packs.software_delivery.contracts import (
    TEST_CASE_STYLES,
    GeneratedTestCase,
    TestCaseStyle,
    TestGenerationResult,
)
from packs.software_delivery.errors import MarkdownExportValidationError
from packs.software_delivery.export_test_cases_markdown import export_test_cases_markdown

TOOL_NAME = "software_delivery.export_test_cases_markdown"
TOOL_DESCRIPTION = (
    "Export structured Software Delivery test cases and citations as Markdown."
)

_ALLOWED_ROOT_KEYS = frozenset({"output_style", "test_cases"})
_ALLOWED_CASE_KEYS = frozenset({"title", "steps", "expected", "references"})
_ALLOWED_REFERENCE_KEYS = frozenset({"source_id", "source_type"})

Formatter = Callable[[TestGenerationResult], str]


class ExportTestCasesMarkdownTool:
    """Implements ``domain.ports.Tool`` for Software Delivery Markdown export."""

    def __init__(
        self,
        *,
        formatter: Formatter = export_test_cases_markdown,
    ) -> None:
        self._formatter = formatter

    @property
    def name(self) -> str:
        return TOOL_NAME

    @property
    def description(self) -> str:
        return TOOL_DESCRIPTION

    def run(self, arguments: Mapping[str, object]) -> str:
        """Validate arguments, export cases, and return Markdown text.

        Raises:
            MarkdownExportValidationError: Invalid or incomplete arguments.
            ToolFailureError: Unexpected failure after valid arguments.
        """
        result = _parse_request(arguments)
        try:
            return self._formatter(result)
        except MarkdownExportValidationError:
            raise
        except ToolFailureError:
            raise
        except Exception as exc:  # noqa: BLE001 - map unexpected failures
            raise ToolFailureError("Markdown export failed") from exc


def _require_nonblank_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarkdownExportValidationError(
            f"{field_name} must be a non-blank string"
        )
    return value


def _parse_request(arguments: Mapping[str, object]) -> TestGenerationResult:
    if not isinstance(arguments, Mapping):
        raise MarkdownExportValidationError(
            f"arguments must be a mapping, got {arguments!r}"
        )
    unknown = set(arguments) - _ALLOWED_ROOT_KEYS
    if unknown:
        raise MarkdownExportValidationError(
            f"unknown argument keys: {sorted(unknown)}"
        )
    if "output_style" not in arguments:
        raise MarkdownExportValidationError("output_style is required")
    if "test_cases" not in arguments:
        raise MarkdownExportValidationError("test_cases is required")

    raw_style = arguments["output_style"]
    if not isinstance(raw_style, str) or raw_style not in TEST_CASE_STYLES:
        raise MarkdownExportValidationError(
            f"output_style must be one of {sorted(TEST_CASE_STYLES)}, "
            f"got {raw_style!r}"
        )
    style: TestCaseStyle = raw_style  # type: ignore[assignment]

    raw_cases = arguments["test_cases"]
    if isinstance(raw_cases, (str, bytes)) or not isinstance(raw_cases, Sequence):
        raise MarkdownExportValidationError(
            f"test_cases must be a sequence, got {raw_cases!r}"
        )
    if len(raw_cases) == 0:
        raise MarkdownExportValidationError("test_cases must be non-empty")

    cases: list[GeneratedTestCase] = []
    for item in raw_cases:
        cases.append(_parse_test_case(item))

    try:
        return TestGenerationResult(style, cases)
    except ValueError as exc:
        raise MarkdownExportValidationError(str(exc)) from exc


def _parse_test_case(item: object) -> GeneratedTestCase:
    if not isinstance(item, Mapping):
        raise MarkdownExportValidationError(
            f"test_cases items must be mappings, got {item!r}"
        )
    for key in item:
        if not isinstance(key, str) or not key.strip():
            raise MarkdownExportValidationError(
                f"test_cases keys must be non-blank strings, got {key!r}"
            )
    unknown = set(item) - _ALLOWED_CASE_KEYS
    if unknown:
        raise MarkdownExportValidationError(
            f"unknown test_cases keys: {sorted(unknown)}"
        )
    for required in ("title", "steps", "expected", "references"):
        if required not in item:
            raise MarkdownExportValidationError(f"{required} is required")

    title = _require_nonblank_str(item["title"], "title")
    expected = _require_nonblank_str(item["expected"], "expected")

    raw_steps = item["steps"]
    if isinstance(raw_steps, (str, bytes)) or not isinstance(raw_steps, Sequence):
        raise MarkdownExportValidationError(
            f"steps must be a sequence, got {raw_steps!r}"
        )
    if len(raw_steps) == 0:
        raise MarkdownExportValidationError("steps must be non-empty")
    steps: list[str] = []
    for step in raw_steps:
        steps.append(_require_nonblank_str(step, "steps items"))

    raw_refs = item["references"]
    if isinstance(raw_refs, (str, bytes)) or not isinstance(raw_refs, Sequence):
        raise MarkdownExportValidationError(
            f"references must be a sequence, got {raw_refs!r}"
        )
    if len(raw_refs) == 0:
        raise MarkdownExportValidationError("references must be non-empty")

    references: list[SourceReference] = []
    for ref_item in raw_refs:
        references.append(_parse_reference(ref_item))

    try:
        return GeneratedTestCase(title, steps, expected, references)
    except ValueError as exc:
        raise MarkdownExportValidationError(str(exc)) from exc


def _parse_reference(item: object) -> SourceReference:
    if not isinstance(item, Mapping):
        raise MarkdownExportValidationError(
            f"references items must be mappings, got {item!r}"
        )
    for key in item:
        if not isinstance(key, str) or not key.strip():
            raise MarkdownExportValidationError(
                f"references keys must be non-blank strings, got {key!r}"
            )
    unknown = set(item) - _ALLOWED_REFERENCE_KEYS
    if unknown:
        raise MarkdownExportValidationError(
            f"unknown references keys: {sorted(unknown)}"
        )
    for required in ("source_id", "source_type"):
        if required not in item:
            raise MarkdownExportValidationError(f"{required} is required")

    source_id = _require_nonblank_str(item["source_id"], "source_id")
    source_type = _require_nonblank_str(item["source_type"], "source_type")
    try:
        return SourceReference(source_id, source_type)
    except DomainValidationError as exc:
        raise MarkdownExportValidationError(str(exc)) from exc
