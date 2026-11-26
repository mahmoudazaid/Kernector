"""HTTP contract for project artifact relationships (#374)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from application.relationship.list import ListArtifactRelationships
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import (
    ArtifactDescriptor,
    ArtifactPart,
    ArtifactRef,
    ContextAssignment,
)
from domain.knowledge import SourceReference, SourceType
from domain.relationship.models import (
    ORIGIN_PROVIDER_DECLARED,
    VERIFICATION_VERIFIED,
    EvidenceRef,
)
from infrastructure.artifact.sql_index import SqlArtifactIndex
from infrastructure.relationship.sql_store import SqlRelationshipStore
from presentation.http.app import create_app
from presentation.http.deps import get_list_artifact_relationships

_PROBLEM = "application/problem+json"
_PROJECT = "prj_orders"


def _descriptor(
    source_id: str,
    key: str,
    *,
    parts: tuple[ArtifactPart, ...] = (),
    contexts: tuple[ContextAssignment, ...] = (
        ContextAssignment("business", "role_default"),
    ),
) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        reference=SourceReference(source_id, SourceType.JIRA),
        revision="r1",
        kind=ArtifactKind.STORY if not parts else ArtifactKind.API_SPEC,
        contexts=contexts,
        external_keys=(key,),
        title=key,
        parts=parts,
    )


def _client(
    path: Path,
) -> tuple[TestClient, SqlRelationshipStore, SqlArtifactIndex]:
    store = SqlRelationshipStore(path, "test-workspace")
    index = SqlArtifactIndex(path, "test-workspace")
    use_case = ListArtifactRelationships(
        store,
        index,
        project_exists=lambda project_id: project_id == _PROJECT,
        project_ids_for=lambda _ref: (_PROJECT,),
        inverse_names={"tests": "tested_by"},
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_list_artifact_relationships] = lambda: use_case
    return TestClient(app, raise_server_exceptions=False), store, index


def test_lists_relationship_fields_and_slash_key(tmp_path: Path) -> None:
    client, store, index = _client(tmp_path / "catalog.sqlite")
    openapi = ArtifactDescriptor(
        reference=SourceReference("inst/api:openapi.yaml", SourceType.JIRA),
        revision="r1",
        kind=ArtifactKind.API_SPEC,
        contexts=(ContextAssignment("operations", "role_default"),),
        external_keys=("openapi", "GET /orders", "listOrders"),
        title="openapi",
        parts=(
            ArtifactPart(
                kind="operation",
                part_key="GET /orders",
                operation_id="listOrders",
            ),
        ),
    )
    index.upsert(openapi)
    index.upsert(_descriptor("inst/PROJ:PROJ-140", "PROJ-140"))
    store.upsert_from_evidence(
        project_id=_PROJECT,
        subject=ArtifactRef(SourceReference("inst/PROJ:PROJ-140", "jira")),
        relation_type="tests",
        object=ArtifactRef(
            SourceReference("inst/api:openapi.yaml", "jira"),
            part_key="GET /orders",
        ),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=EvidenceRef(
            source=SourceReference("inst/PROJ:PROJ-140", "jira"),
            revision="r1",
            locator="field=issuelinks;type=Tests;dir=out;key=openapi",
            extractor_id="jira_explicit_links",
        ),
        seen_at="2026-10-01T12:00:00Z",
    )

    encoded = quote("GET /orders", safe="")
    response = client.get(
        f"/api/v1/projects/{_PROJECT}/artifacts/{encoded}/relationships"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    edge = body[0]
    assert edge["origin"] == ORIGIN_PROVIDER_DECLARED
    assert edge["verification"] == VERIFICATION_VERIFIED
    assert edge["freshness"] == "current"
    assert edge["direction"] == "inward"
    assert edge["relation_type"] == "tested_by"
    assert edge["evidence"][0]["extractor_id"] == "jira_explicit_links"
    assert edge["subject"]["contexts"] == ["business"]
    assert edge["object"]["part_key"] == "GET /orders"
    assert edge["object"]["contexts"] == ["operations"]


def test_unknown_key_and_project_return_problem_json(tmp_path: Path) -> None:
    client, _store, index = _client(tmp_path / "catalog.sqlite")
    index.upsert(_descriptor("inst/PROJ:PROJ-123", "PROJ-123"))

    missing_key = client.get(
        f"/api/v1/projects/{_PROJECT}/artifacts/MISSING-1/relationships"
    )
    assert missing_key.status_code == 404, missing_key.text
    assert missing_key.headers["content-type"].startswith(_PROBLEM)
    assert missing_key.json()["code"] == "artifact_not_found"

    missing_project = client.get(
        "/api/v1/projects/prj_missing/artifacts/PROJ-123/relationships"
    )
    assert missing_project.status_code == 404, missing_project.text
    assert missing_project.headers["content-type"].startswith(_PROBLEM)
    assert missing_project.json()["code"] == "project_not_found"
