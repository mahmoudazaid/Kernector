"""List evidence-backed relationships for a project artifact (#374)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from application.artifact.lookup import _matching_part
from domain.artifact.models import ArtifactRef
from domain.artifact.ports import ArtifactIndex
from domain.knowledge import SourceReference
from domain.project.errors import ProjectNotFoundError
from domain.relationship.errors import ArtifactNotVisibleError
from domain.relationship.models import EvidenceRef, Relationship, UnresolvedKey
from domain.relationship.ports import RelationshipStore

ProjectIdsForSource = Callable[[SourceReference], tuple[str, ...]]
ProjectExists = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class RelationshipEndpointView:
    """One end of a relationship for read APIs."""

    kind: str
    key: str | None
    source_type: str | None
    source_id: str | None
    part_key: str | None
    contexts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelationshipEvidenceView:
    source_type: str
    source_id: str
    revision: str
    locator: str
    extractor_id: str


@dataclass(frozen=True, slots=True)
class RelationshipView:
    """Relationship as seen from a listed artifact key."""

    relationship_id: str
    project_id: str
    relation_type: str
    direction: str
    subject: RelationshipEndpointView
    object: RelationshipEndpointView
    origin: str
    verification: str
    freshness: str
    confidence: float
    evidence: tuple[RelationshipEvidenceView, ...]
    decision_actor: str | None
    decision_at: str | None


class ListArtifactRelationships:
    """Resolve ``key`` within a project and list its relationships."""

    def __init__(
        self,
        store: RelationshipStore,
        index: ArtifactIndex,
        *,
        project_exists: ProjectExists,
        project_ids_for: ProjectIdsForSource,
        inverse_names: Mapping[str, str] | None = None,
    ) -> None:
        self._store = store
        self._index = index
        self._project_exists = project_exists
        self._project_ids_for = project_ids_for
        self._inverse_names = dict(inverse_names or {})

    def execute(
        self,
        project_id: str,
        key: str,
        *,
        filters: Mapping[str, str] | None = None,
    ) -> tuple[RelationshipView, ...]:
        if not self._project_exists(project_id):
            raise ProjectNotFoundError("project not found")
        descriptors = self._index.find_by_key((key,))
        visible = [
            item
            for item in descriptors
            if project_id in self._project_ids_for(item.reference)
        ]
        if not visible:
            raise ArtifactNotVisibleError("artifact not found in project")
        views: list[RelationshipView] = []
        seen: set[str] = set()
        for descriptor in visible:
            part = _matching_part(descriptor, key)
            if part is not None:
                ref = ArtifactRef(descriptor.reference, part_key=part.part_key)
                alias_parts = [key, part.part_key]
                if part.operation_id is not None:
                    alias_parts.append(part.operation_id)
                aliases = tuple(dict.fromkeys(alias_parts))
                edge_groups = (
                    self._store.list_for_artifact(
                        project_id, ref, filters, aliases=aliases
                    ),
                    # Whole-artifact edges stay reachable when listing by a part.
                    self._store.list_for_artifact(
                        project_id,
                        ArtifactRef(descriptor.reference),
                        filters,
                        aliases=(),
                    ),
                )
            else:
                ref = ArtifactRef(descriptor.reference)
                aliases = tuple(dict.fromkeys((key, *descriptor.external_keys)))
                edge_groups = (
                    self._store.list_for_artifact(
                        project_id, ref, filters, aliases=aliases
                    ),
                )
            for edges in edge_groups:
                for edge in edges:
                    if edge.relationship_id in seen:
                        continue
                    kept_evidence = self._visible_evidence(edge, project_id)
                    if not kept_evidence:
                        continue
                    seen.add(edge.relationship_id)
                    views.append(
                        self._to_view(
                            edge,
                            listed=ref,
                            listed_key=key,
                            evidence=kept_evidence,
                            contexts_for=self._contexts_for,
                        )
                    )
        return tuple(views)

    def _visible_evidence(
        self, edge: Relationship, project_id: str
    ) -> tuple[EvidenceRef, ...]:
        """Keep evidence whose source is still associated with ``project_id``."""
        return tuple(
            item
            for item in edge.evidence
            if project_id in self._project_ids_for(item.source)
        )

    def _contexts_for(self, endpoint: ArtifactRef | UnresolvedKey) -> tuple[str, ...]:
        if isinstance(endpoint, UnresolvedKey):
            return ()
        descriptor = self._index.get(endpoint.reference)
        if descriptor is None:
            return ()
        return tuple(item.context for item in descriptor.contexts)

    def _to_view(
        self,
        edge: Relationship,
        *,
        listed: ArtifactRef,
        listed_key: str,
        evidence: tuple[EvidenceRef, ...],
        contexts_for: Callable[[ArtifactRef | UnresolvedKey], tuple[str, ...]],
    ) -> RelationshipView:
        listed_is_object = self._same_endpoint(edge.object, listed, listed_key)
        relation_type = edge.relation_type
        direction = "outward"
        if listed_is_object:
            relation_type = self._inverse_names.get(
                edge.relation_type, f"inverse_of:{edge.relation_type}"
            )
            direction = "inward"
        return RelationshipView(
            relationship_id=edge.relationship_id,
            project_id=edge.project_id,
            relation_type=relation_type,
            direction=direction,
            subject=self._endpoint_view(edge.subject, contexts_for(edge.subject)),
            object=self._endpoint_view(edge.object, contexts_for(edge.object)),
            origin=edge.origin,
            verification=edge.verification,
            freshness=edge.freshness,
            confidence=edge.confidence,
            evidence=tuple(
                RelationshipEvidenceView(
                    source_type=item.source.source_type,
                    source_id=item.source.source_id,
                    revision=item.revision,
                    locator=item.locator,
                    extractor_id=item.extractor_id,
                )
                for item in evidence
            ),
            decision_actor=edge.decision_actor,
            decision_at=edge.decision_at,
        )

    def _endpoint_view(
        self, endpoint: ArtifactRef | UnresolvedKey, contexts: tuple[str, ...]
    ) -> RelationshipEndpointView:
        if isinstance(endpoint, UnresolvedKey):
            return RelationshipEndpointView(
                kind="unresolved",
                key=endpoint.key,
                source_type=None,
                source_id=None,
                part_key=endpoint.part_key,
                contexts=(),
            )
        return RelationshipEndpointView(
            kind="artifact",
            key=None,
            source_type=endpoint.reference.source_type,
            source_id=endpoint.reference.source_id,
            part_key=endpoint.part_key,
            contexts=contexts,
        )

    def _same_endpoint(
        self,
        endpoint: ArtifactRef | UnresolvedKey,
        listed: ArtifactRef,
        listed_key: str,
    ) -> bool:
        if isinstance(endpoint, UnresolvedKey):
            return endpoint.key == listed_key
        if endpoint.reference != listed.reference:
            return False
        if listed.part_key is None:
            return True
        return endpoint.part_key == listed.part_key
