"""Read-only MCP tool listing project artifact relationships (#374)."""

from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from application.relationship.list import ListArtifactRelationships
from domain.errors import ToolArgumentValidationError
from domain.project.errors import ProjectNotFoundError
from domain.relationship.errors import ArtifactNotVisibleError

TOOL_NAME = "core.project_relationships"
TOOL_DESCRIPTION = (
    "List evidence-backed relationships for an artifact key in the caller's "
    "project (origin, verification, freshness, evidence). Read-only."
)


class ProjectRelationshipsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=256)
    project_id: str | None = Field(default=None, max_length=64)


class RelationshipEndpointOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    key: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    part_key: str | None = None
    contexts: list[str]


class RelationshipEvidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str
    source_id: str
    revision: str
    locator: str
    extractor_id: str


class RelationshipOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship_id: str
    project_id: str
    relation_type: str
    direction: str
    subject: RelationshipEndpointOut
    object: RelationshipEndpointOut
    origin: str
    verification: str
    freshness: str
    confidence: float
    evidence: list[RelationshipEvidenceOut]
    decision_actor: str | None = None
    decision_at: str | None = None


class ProjectRelationshipsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationships: list[RelationshipOut]


class ProjectRelationshipsTool:
    """Implements ``domain.ports.Tool`` over :class:`ListArtifactRelationships`."""

    args_schema: type | None = ProjectRelationshipsArgs
    output_schema: type | None = ProjectRelationshipsResult

    def __init__(self, list_relationships: ListArtifactRelationships) -> None:
        self._list_relationships = list_relationships

    @property
    def name(self) -> str:
        return TOOL_NAME

    @property
    def description(self) -> str:
        return TOOL_DESCRIPTION

    def run(self, arguments: Mapping[str, object]) -> str:
        try:
            args = ProjectRelationshipsArgs.model_validate(dict(arguments))
        except Exception as exc:
            raise ToolArgumentValidationError(
                "Invalid project_relationships arguments"
            ) from exc
        from composition.mcp.access import current_caller

        caller = current_caller()
        if caller is None or not caller.project_id:
            raise ToolArgumentValidationError(
                "project_relationships requires a project-scoped caller"
            )
        if args.project_id is not None and args.project_id != caller.project_id:
            raise ToolArgumentValidationError(
                "project_id does not match the caller project"
            )
        try:
            views = self._list_relationships.execute(caller.project_id, args.key)
        except (ProjectNotFoundError, ArtifactNotVisibleError) as exc:
            raise ToolArgumentValidationError(str(exc)) from exc
        result = ProjectRelationshipsResult(
            relationships=[
                RelationshipOut(
                    relationship_id=view.relationship_id,
                    project_id=view.project_id,
                    relation_type=view.relation_type,
                    direction=view.direction,
                    subject=RelationshipEndpointOut(
                        kind=view.subject.kind,
                        key=view.subject.key,
                        source_type=view.subject.source_type,
                        source_id=view.subject.source_id,
                        part_key=view.subject.part_key,
                        contexts=list(view.subject.contexts),
                    ),
                    object=RelationshipEndpointOut(
                        kind=view.object.kind,
                        key=view.object.key,
                        source_type=view.object.source_type,
                        source_id=view.object.source_id,
                        part_key=view.object.part_key,
                        contexts=list(view.object.contexts),
                    ),
                    origin=view.origin,
                    verification=view.verification,
                    freshness=view.freshness,
                    confidence=view.confidence,
                    evidence=[
                        RelationshipEvidenceOut(
                            source_type=item.source_type,
                            source_id=item.source_id,
                            revision=item.revision,
                            locator=item.locator,
                            extractor_id=item.extractor_id,
                        )
                        for item in view.evidence
                    ],
                    decision_actor=view.decision_actor,
                    decision_at=view.decision_at,
                )
                for view in views
            ]
        )
        return json.dumps(result.model_dump(mode="json"), separators=(",", ":"))
