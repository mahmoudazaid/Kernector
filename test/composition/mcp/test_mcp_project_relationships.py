"""Read-only MCP tool ``core.project_relationships`` (#374)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.relationship.list import ListArtifactRelationships
from composition.mcp.access import McpCallerContext, bind_caller
from composition.mcp.project_relationships import TOOL_NAME, ProjectRelationshipsTool
from composition.mcp.tool_registry import (
    TOOL_UNAVAILABLE_CODE,
    McpToolContribution,
    McpToolRegistry,
)
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor, ArtifactRef, ContextAssignment
from domain.errors import ToolArgumentValidationError
from domain.knowledge import SourceReference, SourceType
from domain.relationship.models import (
    ORIGIN_PROVIDER_DECLARED,
    VERIFICATION_VERIFIED,
    EvidenceRef,
)
from infrastructure.artifact.sql_index import SqlArtifactIndex
from infrastructure.relationship.sql_store import SqlRelationshipStore


class _EmptyList:
    def execute(self, project_id: str, key: str, *, filters=None):  # noqa: ANN001
        del project_id, key, filters
        return ()


def _registry(list_relationships: object) -> McpToolRegistry:
    return McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id=TOOL_NAME,
                pack_id=None,
                factory=lambda: ProjectRelationshipsTool(list_relationships),  # type: ignore[arg-type]
            ),
        ),
        enabled_packs=(),
    )


def _descriptor(source_id: str, key: str) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        reference=SourceReference(source_id, SourceType.JIRA),
        revision="r1",
        kind=ArtifactKind.STORY,
        contexts=(ContextAssignment("business", "role_default"),),
        external_keys=(key,),
        title=key,
    )


def test_tool_is_denied_unless_allowlisted() -> None:
    caller = McpCallerContext("ws", "default", "prj_test", frozenset())

    result = _registry(_EmptyList()).invoke_authorized(caller, TOOL_NAME, {"key": "X"})

    assert result.is_error
    assert result.code == TOOL_UNAVAILABLE_CODE


def test_tool_rejects_mismatched_project_id() -> None:
    tool = ProjectRelationshipsTool(_EmptyList())  # type: ignore[arg-type]

    with bind_caller(
        McpCallerContext("ws", "default", "prj_a", frozenset({TOOL_NAME}))
    ):
        with pytest.raises(ToolArgumentValidationError):
            tool.run({"key": "PROJ-123", "project_id": "prj_b"})


def test_tool_returns_relationship_fields_and_hides_lost_association(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite"
    store = SqlRelationshipStore(path, "ws-a")
    index = SqlArtifactIndex(path, "ws-a")
    index.upsert(_descriptor("inst/PROJ:PROJ-140", "PROJ-140"))
    index.upsert(_descriptor("inst/PROJ:PROJ-123", "PROJ-123"))
    index.upsert(_descriptor("inst/OPS:OPS-9", "OPS-9"))
    store.upsert_from_evidence(
        project_id="prj_a",
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
    store.upsert_from_evidence(
        project_id="prj_a",
        subject=ArtifactRef(SourceReference("inst/OPS:OPS-9", "jira")),
        relation_type="blocks",
        object=ArtifactRef(SourceReference("inst/PROJ:PROJ-123", "jira")),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=EvidenceRef(
            source=SourceReference("inst/OPS:OPS-9", "jira"),
            revision="r1",
            locator="field=issuelinks;type=Blocks;dir=out;key=PROJ-123",
            extractor_id="jira_explicit_links",
        ),
        seen_at="2026-10-01T12:00:00Z",
    )
    associations = {
        "inst/PROJ:PROJ-140": ("prj_a",),
        "inst/PROJ:PROJ-123": ("prj_a",),
        "inst/OPS:OPS-9": (),
    }
    tool = ProjectRelationshipsTool(
        ListArtifactRelationships(
            store,
            index,
            project_exists=lambda project_id: project_id == "prj_a",
            project_ids_for=lambda ref: associations.get(ref.source_id, ()),
            inverse_names={"tests": "tested_by", "blocks": "blocked_by"},
        )
    )

    with bind_caller(
        McpCallerContext("ws", "default", "prj_a", frozenset({TOOL_NAME}))
    ):
        raw = tool.run({"key": "PROJ-123"})

    payload = json.loads(raw)
    assert len(payload["relationships"]) == 1
    edge = payload["relationships"][0]
    assert edge["origin"] == ORIGIN_PROVIDER_DECLARED
    assert edge["verification"] == VERIFICATION_VERIFIED
    assert edge["freshness"] == "current"
    assert edge["direction"] == "inward"
    assert edge["relation_type"] == "tested_by"
    assert edge["evidence"][0]["source_id"] == "inst/PROJ:PROJ-140"
    assert edge["subject"]["contexts"] == ["business"]
    assert edge["object"]["contexts"] == ["business"]


def test_wiring_contributes_core_project_relationships() -> None:
    from composition.mcp.wiring import build_mcp_tool_registry
    from infrastructure.config import load_settings

    class _Retrieve:
        def execute(self, request: object) -> object:
            raise AssertionError("not called")

    from composition.mcp.tool_registry import mcp_tool_name

    registry = build_mcp_tool_registry(load_settings(), retrieve=_Retrieve())  # type: ignore[arg-type]
    caller = McpCallerContext("ws", "default", "prj_test", frozenset({TOOL_NAME}))
    assert mcp_tool_name(TOOL_NAME) in {
        item.name for item in registry.list_effective(caller)
    }
