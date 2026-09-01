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
from packs.software_delivery.test_case_generation import serialize_test_generation_result

TOOL_NAME = "software_delivery.export_test_cases_markdown"
TOOL_DESCRIPTION = (
    "Export structured Software Delivery test cases and citations as Markdown."
)

_ALLOWED_ROOT_KEYS = frozenset({"output_style", "test_cases"})
_ALLOWED_CASE_KEYS = frozenset({"title", "steps", "expected", "references"})
_ALLOWED_REFERENCE_KEYS = frozenset({"source_id", "source_type"})

Formatter = Callable[[TestGenerationResult], str]


class ExportTestCasesMarkdownTool:
    """Implements ``domain.ports.Tool`` for Software Delivery test-case export."""

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


def _require_bounded_str(value: object, field_name: str, max_chars: int) -> str:
    text = _require_nonblank_str(value, field_name)
    if len(text) > max_chars:
        raise MarkdownExportValidationError(
            f"{field_name} must be at most {max_chars} characters, got {len(text)}"
        )
    return text


def _validate_mapping_keys(mapping: Mapping[object, object], *, field_name: str) -> None:
    for key in mapping:
        if not isinstance(key, str) or not key.strip():
            raise MarkdownExportValidationError(
                f"{field_name} keys must be non-blank strings, got {key!r}"
            )


def _parse_request(arguments: Mapping[str, object]) -> TestGenerationResult:
    if not isinstance(arguments, Mapping):
        raise MarkdownExportValidationError(
            f"arguments must be a mapping, got {arguments!r}"
        )
    _validate_mapping_keys(arguments, field_name="arguments")
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
    if len(raw_cases) > MAX_GENERATED_CASES:
        raise MarkdownExportValidationError(
            f"test_cases must have at most {MAX_GENERATED_CASES} items, "
            f"got {len(raw_cases)}"
        )

    cases: list[GeneratedTestCase] = []
    for item in raw_cases:
        cases.append(_parse_test_case(item))

    try:
        result = TestGenerationResult(style, cases)
    except ValueError as exc:
        raise MarkdownExportValidationError(str(exc)) from exc
    _validate_result_budget(result)
    return result


def _validate_result_budget(result: TestGenerationResult) -> None:
    try:
        serialize_test_generation_result(result)
    except ToolFailureError as exc:
        raise MarkdownExportValidationError(str(exc)) from exc


def _parse_test_case(item: object) -> GeneratedTestCase:
    if not isinstance(item, Mapping):
        raise MarkdownExportValidationError(
            f"test_cases items must be mappings, got {item!r}"
        )
    _validate_mapping_keys(item, field_name="test_cases")
    unknown = set(item) - _ALLOWED_CASE_KEYS
    if unknown:
        raise MarkdownExportValidationError(
            f"unknown test_cases keys: {sorted(unknown)}"
        )
    for required in ("title", "steps", "expected", "references"):
        if required not in item:
            raise MarkdownExportValidationError(f"{required} is required")

    title = _require_bounded_str(item["title"], "title", MAX_TITLE_CHARS)
    expected = _require_bounded_str(item["expected"], "expected", MAX_EXPECTED_CHARS)

    raw_steps = item["steps"]
    if isinstance(raw_steps, (str, bytes)) or not isinstance(raw_steps, Sequence):
        raise MarkdownExportValidationError(
            f"steps must be a sequence, got {raw_steps!r}"
        )
    if len(raw_steps) == 0:
        raise MarkdownExportValidationError("steps must be non-empty")
    if len(raw_steps) > MAX_STEPS_PER_CASE:
        raise MarkdownExportValidationError(
            f"steps must have at most {MAX_STEPS_PER_CASE} items, got {len(raw_steps)}"
        )
    steps: list[str] = []
    for step in raw_steps:
        steps.append(
            _require_bounded_str(step, "steps items", MAX_STEP_CHARS)
        )

    raw_refs = item["references"]
    if isinstance(raw_refs, (str, bytes)) or not isinstance(raw_refs, Sequence):
        raise MarkdownExportValidationError(
            f"references must be a sequence, got {raw_refs!r}"
        )
    if len(raw_refs) == 0:
        raise MarkdownExportValidationError("references must be non-empty")
    if len(raw_refs) > MAX_EVIDENCE_IDS_PER_CASE:
        raise MarkdownExportValidationError(
            f"references must have at most {MAX_EVIDENCE_IDS_PER_CASE} items, "
            f"got {len(raw_refs)}"
        )

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
    _validate_mapping_keys(item, field_name="references")
    unknown = set(item) - _ALLOWED_REFERENCE_KEYS
    if unknown:
        raise MarkdownExportValidationError(
            f"unknown references keys: {sorted(unknown)}"
        )
    for required in ("source_id", "source_type"):
        if required not in item:
            raise MarkdownExportValidationError(f"{required} is required")

    source_id = _require_bounded_str(
        item["source_id"], "source_id", MAX_SOURCE_ID_CHARS
    )
    source_type = _require_bounded_str(
        item["source_type"], "source_type", MAX_SOURCE_TYPE_CHARS
    )
    try:
        return SourceReference(source_id, source_type)
    except DomainValidationError as exc:
        raise MarkdownExportValidationError(str(exc)) from exc
