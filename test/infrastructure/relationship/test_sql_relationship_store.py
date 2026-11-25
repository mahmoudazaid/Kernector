"""SQLite RelationshipStore: upsert, merge, isolation, decisions (#374)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from domain.artifact.models import ArtifactRef
from domain.knowledge import SourceReference
from domain.relationship.errors import RelationshipInputError
from domain.relationship.models import (
    ORIGIN_INFERRED,
    ORIGIN_PROVIDER_DECLARED,
    VERIFICATION_REJECTED,
    VERIFICATION_UNVERIFIED,
    VERIFICATION_VERIFIED,
    EvidenceRef,
    UnresolvedKey,
)
from infrastructure.relationship.sql_store import SqlRelationshipStore


def _ref(source_id: str) -> ArtifactRef:
    return ArtifactRef(SourceReference(source_id, "jira"))


def _evidence(
    source_id: str = "inst/PROJ:PROJ-140",
    *,
    locator: str = "field=issuelinks;type=Tests;dir=out;key=PROJ-123",
    revision: str = "2026-10-01T12:00:00.000+0000",
) -> EvidenceRef:
    return EvidenceRef(
        source=SourceReference(source_id, "jira"),
        revision=revision,
        locator=locator,
        extractor_id="jira_explicit_links",
    )


@pytest.fixture
def store(tmp_path: Path) -> SqlRelationshipStore:
    return SqlRelationshipStore(tmp_path / "catalog.sqlite", "ws-a")


def test_upsert_is_idempotent_for_same_evidence(store: SqlRelationshipStore) -> None:
    evidence = _evidence()
    first = store.upsert_from_evidence(
        project_id="prj_orders",
        subject=_ref("inst/PROJ:PROJ-140"),
        relation_type="tests",
        object=_ref("inst/PROJ:PROJ-123"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=evidence,
        seen_at="2026-10-01T12:00:00Z",
    )
    second = store.upsert_from_evidence(
        project_id="prj_orders",
        subject=_ref("inst/PROJ:PROJ-140"),
        relation_type="tests",
        object=_ref("inst/PROJ:PROJ-123"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=evidence,
        seen_at="2026-10-01T13:00:00Z",
    )

    listed = store.list_for_artifact("prj_orders", _ref("inst/PROJ:PROJ-123"))
    assert first.relationship_id == second.relationship_id
    assert len(listed) == 1
    assert len(listed[0].evidence) == 1


def test_inward_and_outward_observations_merge_evidence(
    store: SqlRelationshipStore,
) -> None:
    outward = _evidence(
        "inst/PROJ:PROJ-140",
        locator="field=issuelinks;type=Tests;dir=out;key=PROJ-123",
    )
    inward = _evidence(
        "inst/PROJ:PROJ-123",
        locator="field=issuelinks;type=Tests;dir=in;key=PROJ-140",
    )
    store.upsert_from_evidence(
        project_id="prj_orders",
        subject=_ref("inst/PROJ:PROJ-140"),
        relation_type="tests",
        object=_ref("inst/PROJ:PROJ-123"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=outward,
        seen_at="2026-10-01T12:00:00Z",
    )
    store.upsert_from_evidence(
        project_id="prj_orders",
        subject=_ref("inst/PROJ:PROJ-140"),
        relation_type="tests",
        object=_ref("inst/PROJ:PROJ-123"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=inward,
        seen_at="2026-10-01T12:05:00Z",
    )

    listed = store.list_for_artifact("prj_orders", _ref("inst/PROJ:PROJ-140"))
    assert len(listed) == 1
    assert {item.locator for item in listed[0].evidence} == {
        outward.locator,
        inward.locator,
    }


def test_unresolved_resolves_and_merges_atomically(
    store: SqlRelationshipStore,
) -> None:
    store.upsert_from_evidence(
        project_id="prj_orders",
        subject=_ref("inst/PROJ:PROJ-140"),
        relation_type="tests",
        object=UnresolvedKey("PROJ-123"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=_evidence(),
        seen_at="2026-10-01T12:00:00Z",
        object_aliases=("PROJ-123",),
    )
    resolved = store.upsert_from_evidence(
        project_id="prj_orders",
        subject=_ref("inst/PROJ:PROJ-140"),
        relation_type="tests",
        object=_ref("inst/PROJ:PROJ-123"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=_evidence(
            "inst/PROJ:PROJ-123",
            locator="field=issuelinks;type=Tests;dir=in;key=PROJ-140",
        ),
        seen_at="2026-10-02T12:00:00Z",
        object_aliases=("PROJ-123",),
    )

    listed = store.list_for_artifact("prj_orders", _ref("inst/PROJ:PROJ-123"))
    assert len(listed) == 1
    assert listed[0].relationship_id == resolved.relationship_id
    assert isinstance(listed[0].object, ArtifactRef)
    assert listed[0].object.reference.source_id == "inst/PROJ:PROJ-123"
    assert len(listed[0].evidence) == 2


def test_workspace_and_project_isolation(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    a = SqlRelationshipStore(path, "ws-a")
    b = SqlRelationshipStore(path, "ws-b")
    evidence = _evidence()
    a.upsert_from_evidence(
        project_id="prj_orders",
        subject=_ref("inst/PROJ:PROJ-140"),
        relation_type="tests",
        object=_ref("inst/PROJ:PROJ-123"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=evidence,
        seen_at="2026-10-01T12:00:00Z",
    )
    a.upsert_from_evidence(
        project_id="prj_other",
        subject=_ref("inst/PROJ:PROJ-140"),
        relation_type="tests",
        object=_ref("inst/PROJ:PROJ-123"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=evidence,
        seen_at="2026-10-01T12:00:00Z",
    )

    assert len(a.list_for_artifact("prj_orders", _ref("inst/PROJ:PROJ-123"))) == 1
    assert a.list_for_artifact("prj_other", _ref("inst/PROJ:PROJ-123"))[0].project_id == (
        "prj_other"
    )
    assert b.list_for_artifact("prj_orders", _ref("inst/PROJ:PROJ-123")) == ()


def test_confirm_reject_round_trip_preserves_inferred_origin(
    store: SqlRelationshipStore,
) -> None:
    edge = store.upsert_from_evidence(
        project_id="prj_orders",
        subject=_ref("inst/PROJ:PROJ-140"),
        relation_type="relates_to",
        object=_ref("inst/PROJ:PROJ-130"),
        origin=ORIGIN_INFERRED,
        verification=VERIFICATION_UNVERIFIED,
        confidence=0.4,
        freshness="current",
        evidence=_evidence(locator="field=model;span=1"),
        seen_at="2026-10-01T12:00:00Z",
    )
    with pytest.raises(RelationshipInputError):
        store.upsert_from_evidence(
            project_id="prj_orders",
            subject=_ref("inst/PROJ:PROJ-999"),
            relation_type="relates_to",
            object=_ref("inst/PROJ:PROJ-998"),
            origin=ORIGIN_INFERRED,
            verification=VERIFICATION_VERIFIED,
            confidence=0.4,
            freshness="current",
            evidence=_evidence(
                "inst/PROJ:PROJ-999", locator="field=model;span=2"
            ),
            seen_at="2026-10-01T12:00:00Z",
        )

    confirmed = store.apply_decision(
        edge.relationship_id,
        verification=VERIFICATION_VERIFIED,
        actor="operator",
        at=datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc),
        expected_version=edge.decision_version,
    )
    loaded = store.get(edge.relationship_id)
    assert confirmed.origin == ORIGIN_INFERRED
    assert confirmed.verification == VERIFICATION_VERIFIED
    assert confirmed.decision_actor == "operator"
    assert loaded is not None
    assert loaded.verification == VERIFICATION_VERIFIED
    assert loaded.decision_at is not None
    assert loaded.decision_version == edge.decision_version + 1

    rejected = store.apply_decision(
        edge.relationship_id,
        verification=VERIFICATION_REJECTED,
        actor="lead",
        at=datetime(2026, 11, 24, 13, 0, tzinfo=timezone.utc),
        expected_version=loaded.decision_version,
    )
    assert rejected.origin == ORIGIN_INFERRED
    assert rejected.verification == VERIFICATION_REJECTED
    assert rejected.decision_actor == "lead"

    with pytest.raises(RelationshipInputError, match="conflict"):
        store.apply_decision(
            edge.relationship_id,
            verification=VERIFICATION_VERIFIED,
            actor="stale",
            at=datetime(2026, 11, 24, 14, 0, tzinfo=timezone.utc),
            expected_version=loaded.decision_version,
        )


def test_mark_stale_for_evidence_ignores_matching_revision(
    store: SqlRelationshipStore,
) -> None:
    edge = store.upsert_from_evidence(
        project_id="prj_orders",
        subject=_ref("inst/PROJ:PROJ-140"),
        relation_type="tests",
        object=_ref("inst/PROJ:PROJ-123"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=_evidence(revision="r-current"),
        seen_at="2026-10-01T12:00:00Z",
    )
    store.mark_stale_for_evidence(
        SourceReference("inst/PROJ:PROJ-140", "jira"), "r-current"
    )
    loaded = store.get(edge.relationship_id)
    assert loaded is not None
    assert loaded.freshness == "current"
    assert len(loaded.evidence) == 1

    store.upsert_from_evidence(
        project_id="prj_orders",
        subject=_ref("inst/PROJ:PROJ-140"),
        relation_type="tests",
        object=_ref("inst/PROJ:PROJ-123"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=_evidence(revision="r-next"),
        seen_at="2026-10-02T12:00:00Z",
    )
    loaded = store.get(edge.relationship_id)
    assert loaded is not None
    assert len(loaded.evidence) == 1
    assert loaded.evidence[0].revision == "r-next"

    store.mark_stale_for_evidence(
        SourceReference("inst/PROJ:PROJ-140", "jira"), "r-other"
    )
    loaded = store.get(edge.relationship_id)
    assert loaded is not None
    assert loaded.freshness == "stale"
