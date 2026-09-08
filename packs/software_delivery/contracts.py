"""Pack-local contracts for Software Delivery risk scoring and test generation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar

from domain.knowledge import SourceReference
from packs.software_delivery.errors import (
    RiskScoreValidationError,
    TestCaseGenerationValidationError,
)
from packs.software_delivery.limits import (
    MAX_EVIDENCE_ITEMS,
    MAX_EVIDENCE_TEXT_CHARS,
    MAX_SOURCE_ID_CHARS,
    MAX_SOURCE_TYPE_CHARS,
    MAX_TARGET_CHARS,
)

_LEVELS = frozenset({"low", "medium", "high", "critical"})
_LEVELS_DISPLAY = str(sorted(_LEVELS))
TestCaseStyle = Literal["steps", "gherkin"]
TEST_CASE_STYLES: frozenset[str] = frozenset({"steps", "gherkin"})
TEST_CASE_STYLES_DISPLAY = str(sorted(TEST_CASE_STYLES))

_E = TypeVar("_E", bound=Exception)


def _require_text(
    value: object,
    field_name: str,
    error_type: type[_E] = RiskScoreValidationError,
) -> str:
    if not isinstance(value, str):
        raise error_type(
            f"{field_name} must be a non-empty string, got {type(value).__name__}"
        )
    if not value.strip():
        raise error_type(f"{field_name} must be non-empty")
    return value


def _require_sequence(
    value: object,
    field_name: str,
    error_type: type[_E] = RiskScoreValidationError,
) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise error_type(f"{field_name} must be a sequence, got {type(value).__name__}")
    return value


def _require_positive_int(
    value: object,
    field_name: str,
    error_type: type[_E] = RiskScoreValidationError,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise error_type(
            f"{field_name} must be a positive integer, "
            f"got {type(value).__name__}"
        )
    if value <= 0:
        raise error_type(
            f"{field_name} must be a positive integer, got {value}"
        )
    return value


def _require_score(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RiskScoreValidationError(
            f"score must be an int in 0..100, got {type(value).__name__}"
        )
    if not 0 <= value <= 100:
        raise RiskScoreValidationError(f"score must be an int in 0..100, got {value}")
    return value


def _sorted_references(
    references: Sequence[SourceReference],
) -> tuple[SourceReference, ...]:
    return tuple(
        sorted(references, key=lambda ref: (ref.source_type, ref.source_id))
    )


def _sorted_unique_references(
    references: Sequence[SourceReference],
) -> tuple[SourceReference, ...]:
    seen: set[tuple[str, str]] = set()
    unique: list[SourceReference] = []
    for ref in references:
        key = (ref.source_type, ref.source_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return _sorted_references(unique)


def _require_bounded_text(
    value: object,
    field_name: str,
    max_chars: int,
    error_type: type[_E],
) -> str:
    text = _require_text(value, field_name, error_type)
    if len(text) > max_chars:
        raise error_type(
            f"{field_name} must be at most {max_chars} characters, got {len(text)}"
        )
    return text


@dataclass(frozen=True, slots=True)
class RiskEvidence:
    """One evidence item contributing to a risk assessment."""

    reference: SourceReference
    text: str
    is_complete: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.reference, SourceReference):
            raise RiskScoreValidationError(
                "reference must be a SourceReference, "
                f"got {type(self.reference).__name__}"
            )
        _require_text(self.text, "text")
        if not isinstance(self.is_complete, bool):
            raise RiskScoreValidationError(
                f"is_complete must be a bool, got {type(self.is_complete).__name__}"
            )


@dataclass(frozen=True, slots=True)
class RiskAssessmentRequest:
    """Input for scoring risk across a multi-source evidence bundle."""

    target: str
    evidence: Sequence[RiskEvidence]

    def __post_init__(self) -> None:
        _require_text(self.target, "target")
        items = _require_sequence(self.evidence, "evidence")
        if len(items) == 0:
            raise RiskScoreValidationError("evidence must be non-empty")
        normalized: list[RiskEvidence] = []
        for item in items:
            if not isinstance(item, RiskEvidence):
                raise RiskScoreValidationError(
                    f"evidence items must be RiskEvidence, got {type(item).__name__}"
                )
            normalized.append(item)
        object.__setattr__(self, "evidence", tuple(normalized))


@dataclass(frozen=True, slots=True)
class RiskFactor:
    """A contributing risk factor with supporting provenance."""

    factor_id: str
    weight: int
    references: Sequence[SourceReference]

    def __post_init__(self) -> None:
        _require_text(self.factor_id, "factor_id")
        _require_positive_int(self.weight, "weight")
        refs = _require_sequence(self.references, "references")
        if len(refs) == 0:
            raise RiskScoreValidationError("references must be non-empty")
        normalized: list[SourceReference] = []
        for ref in refs:
            if not isinstance(ref, SourceReference):
                raise RiskScoreValidationError(
                    "references items must be SourceReference, "
                    f"got {type(ref).__name__}"
                )
            normalized.append(ref)
        object.__setattr__(self, "references", _sorted_references(normalized))


@dataclass(frozen=True, slots=True)
class RiskAssessmentResult:
    """Structured outcome of a deterministic risk assessment."""

    score: int
    level: str
    factors: Sequence[RiskFactor]
    rationale: str

    def __post_init__(self) -> None:
        _require_score(self.score)
        if not isinstance(self.level, str):
            raise RiskScoreValidationError(
                f"level must be one of {_LEVELS_DISPLAY}, "
                f"got {type(self.level).__name__}"
            )
        if self.level not in _LEVELS:
            raise RiskScoreValidationError(
                f"level must be one of {_LEVELS_DISPLAY}"
            )
        _require_text(self.rationale, "rationale")
        factors = _require_sequence(self.factors, "factors")
        seen_ids: set[str] = set()
        normalized: list[RiskFactor] = []
        for factor in factors:
            if not isinstance(factor, RiskFactor):
                raise RiskScoreValidationError(
                    f"factors items must be RiskFactor, got {type(factor).__name__}"
                )
            if factor.factor_id in seen_ids:
                raise RiskScoreValidationError(
                    "factors items must have unique factor_id"
                )
            seen_ids.add(factor.factor_id)
            normalized.append(factor)
        object.__setattr__(
            self,
            "factors",
            tuple(sorted(normalized, key=lambda item: item.factor_id)),
        )


@dataclass(frozen=True, slots=True)
class TestCaseEvidence:
    """One evidence item for Software Delivery test-case generation."""

    __test__ = False

    reference: SourceReference
    text: str

    def __post_init__(self) -> None:
        err = TestCaseGenerationValidationError
        if not isinstance(self.reference, SourceReference):
            raise err(
                "reference must be a SourceReference, "
                f"got {type(self.reference).__name__}"
            )
        _require_bounded_text(
            self.reference.source_id, "source_id", MAX_SOURCE_ID_CHARS, err
        )
        _require_bounded_text(
            self.reference.source_type, "source_type", MAX_SOURCE_TYPE_CHARS, err
        )
        _require_bounded_text(self.text, "text", MAX_EVIDENCE_TEXT_CHARS, err)


@dataclass(frozen=True, slots=True)
class TestGenerationRequest:
    """Input for generating structured test cases from multi-source evidence."""

    __test__ = False

    target: str
    evidence: Sequence[TestCaseEvidence]
    output_style: TestCaseStyle = "steps"

    def __post_init__(self) -> None:
        err = TestCaseGenerationValidationError
        _require_bounded_text(self.target, "target", MAX_TARGET_CHARS, err)
        items = _require_sequence(self.evidence, "evidence", err)
        if len(items) == 0:
            raise err("evidence must be non-empty")
        if len(items) > MAX_EVIDENCE_ITEMS:
            raise err(
                f"evidence must have at most {MAX_EVIDENCE_ITEMS} items, "
                f"got {len(items)}"
            )
        if not isinstance(self.output_style, str):
            raise err(
                f"output_style must be one of {TEST_CASE_STYLES_DISPLAY}, "
                f"got {type(self.output_style).__name__}"
            )
        if self.output_style not in TEST_CASE_STYLES:
            raise err(f"output_style must be one of {TEST_CASE_STYLES_DISPLAY}")
        normalized: list[TestCaseEvidence] = []
        for item in items:
            if not isinstance(item, TestCaseEvidence):
                raise err(
                    "evidence items must be TestCaseEvidence, "
                    f"got {type(item).__name__}"
                )
            normalized.append(item)
        object.__setattr__(self, "evidence", tuple(normalized))


@dataclass(frozen=True, slots=True)
class GeneratedTestCase:
    """One generated test case with trusted provenance references."""

    title: str
    steps: Sequence[str]
    expected: str
    references: Sequence[SourceReference]

    def __post_init__(self) -> None:
        # Structural checks only; callers that interpret model output must map
        # failures to ToolFailureError, never TestCaseGenerationValidationError.
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be non-empty")
        if isinstance(self.steps, (str, bytes)) or not isinstance(self.steps, Sequence):
            raise ValueError(
                "steps must be a sequence, "
                f"got {type(self.steps).__name__}"
            )
        if len(self.steps) == 0:
            raise ValueError("steps must be non-empty")
        for step in self.steps:
            if not isinstance(step, str) or not step.strip():
                raise ValueError("steps items must be non-empty strings")
        if not isinstance(self.expected, str) or not self.expected.strip():
            raise ValueError("expected must be non-empty")
        if isinstance(self.references, (str, bytes)) or not isinstance(
            self.references, Sequence
        ):
            raise ValueError(
                "references must be a sequence, "
                f"got {type(self.references).__name__}"
            )
        if len(self.references) == 0:
            raise ValueError("references must be non-empty")
        normalized: list[SourceReference] = []
        for ref in self.references:
            if not isinstance(ref, SourceReference):
                raise ValueError(
                    "references items must be SourceReference, "
                    f"got {type(ref).__name__}"
                )
            normalized.append(ref)
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "references", _sorted_unique_references(normalized))


@dataclass(frozen=True, slots=True)
class TestGenerationResult:
    """Structured test-case generation outcome."""

    __test__ = False

    output_style: TestCaseStyle
    test_cases: Sequence[GeneratedTestCase]

    def __post_init__(self) -> None:
        if self.output_style not in TEST_CASE_STYLES:
            raise ValueError(
                f"output_style must be one of {TEST_CASE_STYLES_DISPLAY}"
            )
        cases = self.test_cases
        if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
            raise ValueError(
                "test_cases must be a sequence, "
                f"got {type(cases).__name__}"
            )
        if len(cases) == 0:
            raise ValueError("test_cases must be non-empty")
        normalized: list[GeneratedTestCase] = []
        for case in cases:
            if not isinstance(case, GeneratedTestCase):
                raise ValueError(
                    "test_cases items must be GeneratedTestCase, "
                    f"got {type(case).__name__}"
                )
            normalized.append(case)
        # Preserve model order — do not sort.
        object.__setattr__(self, "test_cases", tuple(normalized))
