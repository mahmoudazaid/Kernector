"""Tool adapter for ``software_delivery.generate_test_cases``."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from domain.errors import DomainValidationError, ToolFailureError
from domain.knowledge import SourceReference
from domain.ports import ChatModel
from packs.software_delivery.contracts import (
    TEST_CASE_STYLES,
    TestCaseEvidence,
    TestCaseStyle,
    TestGenerationRequest,
    TestGenerationResult,
)
from packs.software_delivery.errors import TestCaseGenerationValidationError
from packs.software_delivery.test_case_generation import (
    generate_test_cases,
    serialize_test_generation_result,
)

TOOL_NAME = "software_delivery.generate_test_cases"
TOOL_DESCRIPTION = (
    "Generate structured test cases from an assessment target and "
    "multi-source evidence bundle."
)

_ALLOWED_EVIDENCE_KEYS = frozenset({"source_id", "source_type", "text"})
_ALLOWED_ROOT_KEYS = frozenset({"target", "evidence", "output_style"})

Generator = Callable[[TestGenerationRequest, ChatModel], TestGenerationResult]


class GenerateTestCasesTool:
    """Implements ``domain.ports.Tool`` for Software Delivery test generation."""

    def __init__(
        self,
        chat_model: ChatModel,
        *,
        generator: Generator = generate_test_cases,
    ) -> None:
        self._chat_model = chat_model
        self._generator = generator

    @property
    def name(self) -> str:
        return TOOL_NAME

    @property
    def description(self) -> str:
        return TOOL_DESCRIPTION

    def run(self, arguments: Mapping[str, object]) -> str:
        """Validate arguments, generate cases, and return JSON text.

        Raises:
            TestCaseGenerationValidationError: Invalid or incomplete arguments.
            ToolFailureError: Model/provider or output validation failure.
        """
        request = _parse_request(arguments)
        try:
            result = self._generator(request, self._chat_model)
        except TestCaseGenerationValidationError:
            raise
        except ToolFailureError:
            raise
        except Exception as exc:  # noqa: BLE001 - map unexpected failures
            raise ToolFailureError("Test case generation failed") from exc
        return serialize_test_generation_result(result)


def _require_nonblank_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TestCaseGenerationValidationError(
            f"{field_name} must be a non-blank string"
        )
    return value


def _parse_request(arguments: Mapping[str, object]) -> TestGenerationRequest:
    if not isinstance(arguments, Mapping):
        raise TestCaseGenerationValidationError(
            f"arguments must be a mapping, got {arguments!r}"
        )
    unknown = set(arguments) - _ALLOWED_ROOT_KEYS
    if unknown:
        raise TestCaseGenerationValidationError(
            f"unknown argument keys: {sorted(unknown)}"
        )
    if "target" not in arguments:
        raise TestCaseGenerationValidationError("target is required")
    if "evidence" not in arguments:
        raise TestCaseGenerationValidationError("evidence is required")

    target = _require_nonblank_str(arguments["target"], "target")
    raw_evidence = arguments["evidence"]
    if isinstance(raw_evidence, (str, bytes)) or not isinstance(
        raw_evidence, Sequence
    ):
        raise TestCaseGenerationValidationError(
            f"evidence must be a sequence, got {raw_evidence!r}"
        )

    style: TestCaseStyle = "steps"
    if "output_style" in arguments:
        raw_style = arguments["output_style"]
        if not isinstance(raw_style, str) or raw_style not in TEST_CASE_STYLES:
            raise TestCaseGenerationValidationError(
                f"output_style must be one of {sorted(TEST_CASE_STYLES)}, "
                f"got {raw_style!r}"
            )
        style = raw_style  # type: ignore[assignment]

    evidence: list[TestCaseEvidence] = []
    for item in raw_evidence:
        evidence.append(_parse_evidence_item(item))
    return TestGenerationRequest(target, evidence, style)


def _parse_evidence_item(item: object) -> TestCaseEvidence:
    if not isinstance(item, Mapping):
        raise TestCaseGenerationValidationError(
            f"evidence items must be mappings, got {item!r}"
        )
    for key in item:
        if not isinstance(key, str) or not key.strip():
            raise TestCaseGenerationValidationError(
                f"evidence keys must be non-blank strings, got {key!r}"
            )
    unknown = set(item) - _ALLOWED_EVIDENCE_KEYS
    if unknown:
        raise TestCaseGenerationValidationError(
            f"unknown evidence keys: {sorted(unknown)}"
        )
    for required in ("source_id", "source_type", "text"):
        if required not in item:
            raise TestCaseGenerationValidationError(f"{required} is required")

    source_id = _require_nonblank_str(item["source_id"], "source_id")
    source_type = _require_nonblank_str(item["source_type"], "source_type")
    text = _require_nonblank_str(item["text"], "text")
    try:
        reference = SourceReference(source_id, source_type)
    except DomainValidationError as exc:
        raise TestCaseGenerationValidationError(str(exc)) from exc
    try:
        return TestCaseEvidence(reference, text)
    except TestCaseGenerationValidationError:
        raise
