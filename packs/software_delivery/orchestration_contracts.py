"""Pack-local orchestration request/response contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeVar

from packs.software_delivery.contracts import (
    RiskAssessmentResult,
    TEST_CASE_STYLES,
    TestCaseStyle,
    TestGenerationResult,
)
from packs.software_delivery.errors import OrchestrationValidationError
from packs.software_delivery.evidence_bundle import EvidenceBundle
from packs.software_delivery.orchestration_policy import SoftwareDeliveryIntent

_E = TypeVar("_E", bound=Exception)


def _require_text(
    value: object,
    field_name: str,
    error_type: type[_E] = OrchestrationValidationError,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"{field_name} must be non-empty")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class OrchestrateSoftwareDeliveryRequest:
    """Input for Software Delivery orchestration over a retrieved bundle.

    Attributes:
        intent (SoftwareDeliveryIntent): Ordered tool chain to run.
        target (str): Assessment subject forwarded to each tool.
        evidence (EvidenceBundle): Already-retrieved multi-source evidence.
        output_style (TestCaseStyle): Generate/export style when chained.
    """

    intent: SoftwareDeliveryIntent
    target: str
    evidence: EvidenceBundle
    output_style: TestCaseStyle = "steps"

    def __post_init__(self) -> None:
        if not isinstance(self.intent, SoftwareDeliveryIntent):
            raise OrchestrationValidationError(
                f"intent must be a SoftwareDeliveryIntent, got {self.intent!r}"
            )
        _require_text(self.target, "target")
        if not isinstance(self.evidence, EvidenceBundle):
            raise OrchestrationValidationError(
                f"evidence must be an EvidenceBundle, got {self.evidence!r}"
            )
        if (
            not isinstance(self.output_style, str)
            or self.output_style not in TEST_CASE_STYLES
        ):
            raise OrchestrationValidationError(
                f"output_style must be one of {sorted(TEST_CASE_STYLES)}, "
                f"got {self.output_style!r}"
            )


@dataclass(frozen=True, slots=True)
class RiskScoreOutcome:
    """Typed outcome of the risk-scoring step."""

    assessment: RiskAssessmentResult


@dataclass(frozen=True, slots=True)
class GenerateTestsOutcome:
    """Typed outcome of the test-generation step."""

    result: TestGenerationResult


@dataclass(frozen=True, slots=True)
class ExportMarkdownOutcome:
    """Typed outcome of the Markdown export step."""

    markdown: str


SoftwareDeliveryOutcome = RiskScoreOutcome | GenerateTestsOutcome | ExportMarkdownOutcome


@dataclass(frozen=True, slots=True)
class OrchestrateSoftwareDeliveryResponse:
    """Typed orchestration result with deserialized step outcomes.

    Attributes:
        summary (str): Deterministic description of what ran.
        outcomes (Sequence[SoftwareDeliveryOutcome]): Ordered typed step results.
    """

    summary: str
    outcomes: Sequence[SoftwareDeliveryOutcome] = ()

    def __post_init__(self) -> None:
        _require_text(self.summary, "summary")
        if isinstance(self.outcomes, (str, bytes)) or not isinstance(
            self.outcomes, Sequence
        ):
            raise OrchestrationValidationError(
                f"outcomes must be a sequence, got {self.outcomes!r}"
            )
        normalized: list[SoftwareDeliveryOutcome] = []
        for item in self.outcomes:
            if not isinstance(
                item, (RiskScoreOutcome, GenerateTestsOutcome, ExportMarkdownOutcome)
            ):
                raise OrchestrationValidationError(
                    f"outcomes items must be typed step outcomes, got {item!r}"
                )
            normalized.append(item)
        object.__setattr__(self, "outcomes", tuple(normalized))
