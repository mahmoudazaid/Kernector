"""Deterministic multi-source software-delivery risk scoring."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from domain.knowledge import SourceReference
from packs.software_delivery.contracts import (
    RiskAssessmentRequest,
    RiskAssessmentResult,
    RiskEvidence,
    RiskFactor,
)
from packs.software_delivery.errors import RiskScoreValidationError

STORY_SOURCE_TYPES = frozenset({"story", "user_story"})

_FACTOR_WEIGHTS: dict[str, int] = {
    "missing_acceptance_criteria": 25,
    "ambiguous_language": 15,
    "external_dependency": 20,
    "security_sensitive": 20,
    "data_or_migration": 15,
    "known_defect_or_failure": 15,
    "high_severity": 10,
}

_EMPTY_RATIONALE = (
    "No elevated signals were detected in the supplied evidence."
)

_AC_MARKER = re.compile(
    r"\bacceptance(?:\s+criteria)?\b|\bgiven\b.+\bwhen\b.+\bthen\b",
    re.IGNORECASE | re.DOTALL,
)

_AMBIGUOUS = re.compile(
    r"\b(?:tbd|tbc|todo|unclear|somehow|as appropriate|"
    r"to be (?:decided|defined|determined)|etc\.?)\b",
    re.IGNORECASE,
)

_EXTERNAL = re.compile(
    r"\b(?:blocked by|depends on|dependency on|third[-\s]party|"
    r"external (?:api|system|service)|waiting (?:on|for))\b",
    re.IGNORECASE,
)
_EXTERNAL_NEGATION = re.compile(
    r"\bno\s+external\s+dependenc(?:y|ies)\b",
    re.IGNORECASE,
)

_SECURITY = re.compile(
    r"\b(?:security|pii|gdpr|pci|oauth|authentication|authorization|"
    r"credential|encrypt(?:ion|ed)?)\b",
    re.IGNORECASE,
)
_SECURITY_NEGATION = re.compile(
    r"\bnot\s+security[-\s]?sensitive\b",
    re.IGNORECASE,
)

_MIGRATION = re.compile(
    r"\b(?:migrat\w*|schema\s+change|backfill|breaking\s+change|data\s+loss)\b",
    re.IGNORECASE,
)
_MIGRATION_NEGATION = re.compile(
    r"\bwithout\s+data\s+migration\b",
    re.IGNORECASE,
)

_DEFECT = re.compile(
    r"\b(?:known\s+(?:issue|bug|defect)s?|regression|flaky|"
    r"failing\s+test|test\s+failure)\b",
    re.IGNORECASE,
)
_DEFECT_NEGATION = re.compile(
    r"\bno\s+known\s+defects?\b",
    re.IGNORECASE,
)

_HIGH_SEVERITY = re.compile(
    r"(?:\bseverity\b.{0,40}\b(?:high|critical)\b|"
    r"\b(?:high|critical)\b.{0,40}\bseverity\b|"
    r"\bcritical\b)",
    re.IGNORECASE,
)


def risk_level(score: object) -> str:
    """Map a bounded integer score to a risk level.

    Args:
        score: Integer score in ``0..100``.

    Returns:
        One of ``low``, ``medium``, ``high``, or ``critical``.

    Raises:
        RiskScoreValidationError: If ``score`` is not an int in range.
    """
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
        raise RiskScoreValidationError(
            f"score must be an int in 0..100, got {score!r}"
        )
    if score <= 24:
        return "low"
    if score <= 49:
        return "medium"
    if score <= 74:
        return "high"
    return "critical"


def score_risk(request: RiskAssessmentRequest) -> RiskAssessmentResult:
    """Score delivery risk from a normalized multi-source evidence bundle.

    Args:
        request: Validated assessment request.

    Returns:
        Deterministic score, level, factors with provenance, and rationale.
    """
    if not isinstance(request, RiskAssessmentRequest):
        raise RiskScoreValidationError(
            f"request must be a RiskAssessmentRequest, got {request!r}"
        )

    collected: dict[str, list[SourceReference]] = {
        factor_id: [] for factor_id in _FACTOR_WEIGHTS
    }

    for item in request.evidence:
        _collect_positive_signals(item, collected)
        _collect_missing_acceptance(item, collected)

    factors = _build_factors(collected)
    raw = sum(factor.weight for factor in factors)
    score = min(100, raw)
    level = risk_level(score)
    rationale = _build_rationale(score, level, factors)
    return RiskAssessmentResult(score, level, factors, rationale)


def _collect_missing_acceptance(
    item: RiskEvidence, collected: dict[str, list[SourceReference]]
) -> None:
    source_type = item.reference.source_type.strip().lower()
    if source_type not in STORY_SOURCE_TYPES:
        return
    if not item.is_complete:
        return
    if _AC_MARKER.search(item.text):
        return
    collected["missing_acceptance_criteria"].append(item.reference)


def _collect_positive_signals(
    item: RiskEvidence, collected: dict[str, list[SourceReference]]
) -> None:
    text = item.text
    ref = item.reference

    if _AMBIGUOUS.search(text):
        collected["ambiguous_language"].append(ref)

    if _EXTERNAL.search(text) and not _EXTERNAL_NEGATION.search(text):
        collected["external_dependency"].append(ref)

    if _SECURITY.search(text) and not _SECURITY_NEGATION.search(text):
        collected["security_sensitive"].append(ref)

    if _MIGRATION.search(text) and not _MIGRATION_NEGATION.search(text):
        collected["data_or_migration"].append(ref)

    if _DEFECT.search(text) and not _DEFECT_NEGATION.search(text):
        collected["known_defect_or_failure"].append(ref)

    if _HIGH_SEVERITY.search(text):
        collected["high_severity"].append(ref)


def _build_factors(
    collected: dict[str, list[SourceReference]],
) -> tuple[RiskFactor, ...]:
    factors: list[RiskFactor] = []
    for factor_id, weight in _FACTOR_WEIGHTS.items():
        refs = collected[factor_id]
        if not refs:
            continue
        unique = _unique_sorted_refs(refs)
        factors.append(RiskFactor(factor_id, weight, unique))
    return tuple(sorted(factors, key=lambda item: item.factor_id))


def _unique_sorted_refs(
    refs: Sequence[SourceReference],
) -> tuple[SourceReference, ...]:
    seen: set[tuple[str, str]] = set()
    unique: list[SourceReference] = []
    for ref in refs:
        key = (ref.source_type, ref.source_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return tuple(sorted(unique, key=lambda item: (item.source_type, item.source_id)))


def _build_rationale(
    score: int, level: str, factors: Iterable[RiskFactor]
) -> str:
    ordered = tuple(factors)
    if not ordered:
        return _EMPTY_RATIONALE
    parts: list[str] = []
    for factor in ordered:
        refs = ", ".join(
            f"{ref.source_type}:{ref.source_id}" for ref in factor.references
        )
        parts.append(f"{factor.factor_id}[{refs}]")
    return (
        f"Risk score {score} ({level}) from factors: {', '.join(parts)}."
    )
