"""ListArtifactRelationships project scope and inverse display (#374)."""

from __future__ import annotations

from pathlib import Path

import pytest

from application.relationship.list import ListArtifactRelationships
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor, ArtifactRef, ContextAssignment
from domain.knowledge import SourceReference, SourceType
from domain.project.errors import ProjectNotFoundError
from domain.relationship.errors import ArtifactNotVisibleError
from domain.relationship.models import (
    ORIGIN_PROVIDER_DECLARED,
    VERIFICATION_VERIFIED,
    EvidenceRef,
)
from infrastructure.artifact.sql_index import SqlArtifactIndex
from infrastructure.relationship.sql_store import SqlRelationshipStore


def _descriptor(source_id: str, key: str) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        reference=SourceReference(source_id, SourceType.JIRA),
        revision="r1",
        kind=ArtifactKind.STORY,
        contexts=(ContextAssignment("business", "role_default"),),
        external_keys=(key,),
        title=key,
    )


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "catalog.sqlite"


@pytest.fixture
def index(path: Path) -> SqlArtifactIndex:
    return SqlArtifactIndex(path, "ws-a")


@pytest.fixture
def store(path: Path) -> SqlRelationshipStore:
    return SqlRelationshipStore(path, "ws-a")


def test_lists_inverse_relation_from_object_side(
    index: SqlArtifactIndex, store: SqlRelationshipStore
) -> None:
    index.upsert(_descriptor("inst/PROJ:PROJ-140", "PROJ-140"))
    index.upsert(_descriptor("inst/PROJ:PROJ-123", "PROJ-123"))
    store.upsert_from_evidence(
        project_id="prj_orders",
        subject=ArtifactRef(SourceReference("inst/PROJ:PROJ-140", "jira")),
        relation_type="tests",
        object=ArtifactRef(SourceReference("inst/PROJ:PROJ-123", "jira")),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=EvidenceRef(
            source=SourceReference("inst/PROJ:PROJ-140", "jira"),
            revision="r1",
            locator="field=issuelinks;type=Tests;dir=out;key=PROJ-123",
            extractor_id="jira_explicit_links",
        ),
        seen_at="2026-10-01T12:00:00Z",
    )
    use_case = ListArtifactRelationships(
        store,
        index,
        project_exists=lambda project_id: project_id == "prj_orders",
        project_ids_for=lambda _ref: ("prj_orders",),
    )

    views = use_case.execute("prj_orders", "PROJ-123")

    assert len(views) == 1
    assert views[0].relation_type == "tested_by"
    assert views[0].direction == "inward"
    assert views[0].origin == ORIGIN_PROVIDER_DECLARED
    assert views[0].subject.contexts == ("business",)


def test_rejects_unknown_project_and_invisible_key(
    index: SqlArtifactIndex, store: SqlRelationshipStore
) -> None:
    index.upsert(_descriptor("inst/PROJ:PROJ-123", "PROJ-123"))
    use_case = ListArtifactRelationships(
        store,
        index,
        project_exists=lambda project_id: project_id == "prj_orders",
        project_ids_for=lambda _ref: (),
    )

    with pytest.raises(ProjectNotFoundError):
        use_case.execute("prj_missing", "PROJ-123")
    with pytest.raises(ArtifactNotVisibleError):
        use_case.execute("prj_orders", "PROJ-123")
