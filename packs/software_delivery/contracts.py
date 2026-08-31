"""Pack-local contracts for multi-source software-delivery risk scoring."""

from collections.abc import Sequence
from dataclasses import dataclass

from domain.knowledge import SourceReference
from packs.software_delivery.errors import RiskScoreValidationError

_LEVELS = frozenset({"low", "medium", "high", "critical"})


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RiskScoreValidationError(f"{field_name} must be non-empty")
    return value


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise RiskScoreValidationError(
            f"{field_name} must be a sequence, got {value!r}"
        )
    return value


def _require_positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RiskScoreValidationError(
            f"{field_name} must be a positive integer, got {value!r}"
        )
    return value


def _require_score(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise RiskScoreValidationError(
            f"score must be an int in 0..100, got {value!r}"
        )
    return value


def _sorted_references(
    references: Sequence[SourceReference],
) -> tuple[SourceReference, ...]:
    return tuple(
        sorted(references, key=lambda ref: (ref.source_type, ref.source_id))
    )


@dataclass(frozen=True, slots=True)
class RiskEvidence:
    """One evidence item contributing to a risk assessment."""

    reference: SourceReference
    text: str
    is_complete: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.reference, SourceReference):
            raise RiskScoreValidationError(
                f"reference must be a SourceReference, got {self.reference!r}"
            )
        _require_text(self.text, "text")
        if not isinstance(self.is_complete, bool):
            raise RiskScoreValidationError(
                f"is_complete must be a bool, got {self.is_complete!r}"
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
                    f"evidence items must be RiskEvidence, got {item!r}"
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
                    f"references items must be SourceReference, got {ref!r}"
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
        if not isinstance(self.level, str) or self.level not in _LEVELS:
            raise RiskScoreValidationError(
                f"level must be one of {sorted(_LEVELS)}, got {self.level!r}"
            )
        _require_text(self.rationale, "rationale")
        factors = _require_sequence(self.factors, "factors")
        seen_ids: set[str] = set()
        normalized: list[RiskFactor] = []
        for factor in factors:
            if not isinstance(factor, RiskFactor):
                raise RiskScoreValidationError(
                    f"factors items must be RiskFactor, got {factor!r}"
                )
            if factor.factor_id in seen_ids:
                raise RiskScoreValidationError(
                    f"duplicate factor_id: {factor.factor_id!r}"
                )
            seen_ids.add(factor.factor_id)
            normalized.append(factor)
        object.__setattr__(
            self,
            "factors",
            tuple(sorted(normalized, key=lambda item: item.factor_id)),
        )
