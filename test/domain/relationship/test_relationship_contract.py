"""Relationship and evidence domain invariants (#374, ADR 0011)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.artifact.models import ArtifactRef
from domain.errors import DomainValidationError
from domain.knowledge import SourceReference
from domain.relationship.errors import RelationshipInputError
from domain.relationship.models import (
    ORIGIN_HUMAN_CONFIRMED,
    ORIGIN_INFERRED,
    ORIGIN_PROVIDER_DECLARED,
    VERIFICATION_REJECTED,
    VERIFICATION_UNVERIFIED,
    VERIFICATION_VERIFIED,
    EvidenceRef,
    Relationship,
    UnresolvedKey,
)


def _reference(source_id: str = "inst/PROJ:PROJ-140") -> SourceReference:
    return SourceReference(source_id, "jira")


def _artifact(source_id: str = "inst/PROJ:PROJ-140") -> ArtifactRef:
    return ArtifactRef(_reference(source_id))


def _evidence(**overrides: object) -> EvidenceRef:
    values: dict[str, object] = {
        "source": _reference(),
        "revision": "2026-10-01T12:00:00.000+0000",
        "locator": "field=issuelinks;type=Tests;dir=out;key=PROJ-123",
        "extractor_id": "jira_explicit_links",
    }
    values.update(overrides)
    return EvidenceRef(**values)  # type: ignore[arg-type]


def _relationship(**overrides: object) -> Relationship:
    values: dict[str, object] = {
        "relationship_id": "rel_abc123",
        "project_id": "prj_orders",
        "subject": _artifact("inst/PROJ:PROJ-140"),
        "relation_type": "tests",
        "object": _artifact("inst/PROJ:PROJ-123"),
        "origin": ORIGIN_PROVIDER_DECLARED,
        "verification": VERIFICATION_VERIFIED,
        "confidence": 1.0,
        "freshness": "current",
        "evidence": (_evidence(),),
        "first_seen_at": "2026-10-01T12:00:00Z",
        "last_verified_at": "2026-10-01T12:00:00Z",
    }
    values.update(overrides)
    return Relationship(**values)  # type: ignore[arg-type]


def test_provider_declared_relationship_accepts_valid_contract() -> None:
    edge = _relationship()

    assert edge.origin == ORIGIN_PROVIDER_DECLARED
    assert edge.verification == VERIFICATION_VERIFIED
    assert edge.object == _artifact("inst/PROJ:PROJ-123")
    assert len(edge.evidence) == 1


def test_relationship_may_target_unresolved_key_or_artifact_part() -> None:
    unresolved = _relationship(object=UnresolvedKey("PROJ-999"))
    part = _relationship(
        object=ArtifactRef(_reference("inst/PROJ:PROJ-123"), part_key="POST /orders")
    )

    assert unresolved.object == UnresolvedKey("PROJ-999")
    assert isinstance(part.object, ArtifactRef)
    assert part.object.part_key == "POST /orders"


def test_relationship_rejects_empty_evidence() -> None:
    with pytest.raises(RelationshipInputError, match="evidence"):
        _relationship(evidence=())


def test_inferred_relationship_must_start_unverified() -> None:
    with pytest.raises(RelationshipInputError, match="inferred"):
        _relationship(
            origin=ORIGIN_INFERRED,
            verification=VERIFICATION_VERIFIED,
            confidence=0.4,
        )
    with pytest.raises(RelationshipInputError, match="inferred"):
        _relationship(
            origin=ORIGIN_INFERRED,
            verification=VERIFICATION_REJECTED,
            confidence=0.4,
        )

    edge = _relationship(
        origin=ORIGIN_INFERRED,
        verification=VERIFICATION_UNVERIFIED,
        confidence=0.4,
        last_verified_at=None,
    )
    assert edge.verification == VERIFICATION_UNVERIFIED


def test_confirm_preserves_inferred_origin_and_records_actor() -> None:
    edge = _relationship(
        origin=ORIGIN_INFERRED,
        verification=VERIFICATION_UNVERIFIED,
        confidence=0.4,
        last_verified_at=None,
        decision_actor=None,
        decision_at=None,
    )
    decided_at = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)

    confirmed = edge.confirm(actor="operator", at=decided_at)

    assert confirmed.origin == ORIGIN_INFERRED
    assert confirmed.verification == VERIFICATION_VERIFIED
    assert confirmed.decision_actor == "operator"
    assert confirmed.decision_at == "2026-11-24T12:00:00+00:00"
    assert confirmed.last_verified_at == "2026-11-24T12:00:00+00:00"


def test_reject_preserves_inferred_origin_and_records_actor() -> None:
    edge = _relationship(
        origin=ORIGIN_INFERRED,
        verification=VERIFICATION_UNVERIFIED,
        confidence=0.4,
        last_verified_at=None,
    )
    decided_at = datetime(2026, 11, 24, 13, 0, tzinfo=timezone.utc)

    rejected = edge.reject(actor="operator", at=decided_at)

    assert rejected.origin == ORIGIN_INFERRED
    assert rejected.verification == VERIFICATION_REJECTED
    assert rejected.decision_actor == "operator"
    assert rejected.decision_at == "2026-11-24T13:00:00+00:00"


def test_confirm_may_reverse_rejected_decision() -> None:
    edge = _relationship(
        origin=ORIGIN_INFERRED,
        verification=VERIFICATION_UNVERIFIED,
        confidence=0.4,
        last_verified_at=None,
    ).reject(
        actor="operator",
        at=datetime(2026, 11, 24, 13, 0, tzinfo=timezone.utc),
    )

    confirmed = edge.confirm(
        actor="lead",
        at=datetime(2026, 11, 24, 14, 0, tzinfo=timezone.utc),
    )

    assert confirmed.verification == VERIFICATION_VERIFIED
    assert confirmed.decision_actor == "lead"


def test_human_confirmed_starts_verified() -> None:
    edge = _relationship(
        origin=ORIGIN_HUMAN_CONFIRMED,
        verification=VERIFICATION_VERIFIED,
        decision_actor="operator",
        decision_at="2026-11-24T12:00:00+00:00",
    )
    assert edge.origin == ORIGIN_HUMAN_CONFIRMED


def test_evidence_ref_rejects_blank_locator() -> None:
    with pytest.raises(RelationshipInputError):
        _evidence(locator="   ")


def test_unresolved_key_rejects_blank() -> None:
    with pytest.raises(RelationshipInputError):
        UnresolvedKey("  ")


def test_relationship_input_error_is_domain_validation_error() -> None:
    assert issubclass(RelationshipInputError, DomainValidationError)
