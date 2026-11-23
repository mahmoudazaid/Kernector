"""Exact artifact lookup by external key (#373)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from application.errors import ApplicationValidationError
from domain.artifact.models import ArtifactDescriptor, ArtifactPart
from domain.artifact.ports import ArtifactIndex
from domain.knowledge import CatalogDocument, SourceReference
from domain.ports import DocumentCatalog

ProjectIdsForSource = Callable[[SourceReference], tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class ArtifactLookupMatch:
    """One exact-key hit with live catalog state and confirmed project ids."""

    descriptor: ArtifactDescriptor
    document: CatalogDocument | None
    matched_key: str
    part: ArtifactPart | None
    project_ids: tuple[str, ...]


def _matching_part(
    descriptor: ArtifactDescriptor, key: str
) -> ArtifactPart | None:
    for part in descriptor.parts:
        if part.part_key == key or part.operation_id == key:
            return part
    return None


def _matched_key(descriptor: ArtifactDescriptor, keys: Sequence[str]) -> str | None:
    key_set = set(keys)
    for key in descriptor.external_keys:
        if key in key_set:
            return key
    for part in descriptor.parts:
        if part.part_key in key_set:
            return part.part_key
        if part.operation_id is not None and part.operation_id in key_set:
            return part.operation_id
    return None


class LookupArtifacts:
    """Independent index lookup; project membership is resolved live via #372."""

    def __init__(
        self,
        index: ArtifactIndex,
        catalog: DocumentCatalog,
        *,
        project_ids_for: ProjectIdsForSource,
    ) -> None:
        self._index = index
        self._catalog = catalog
        self._project_ids_for = project_ids_for

    def execute(
        self,
        keys: Sequence[str],
        *,
        project_id: str | None = None,
        contexts: Sequence[str] = (),
    ) -> tuple[ArtifactLookupMatch, ...]:
        """Return matches for ``keys``, optionally scoped by project and contexts."""
        normalized = tuple(
            key.strip() for key in keys if isinstance(key, str) and key.strip()
        )
        if not normalized:
            raise ApplicationValidationError("keys must be a non-empty sequence")
        if project_id is not None and (
            not isinstance(project_id, str) or not project_id.strip()
        ):
            raise ApplicationValidationError("project_id must be a non-empty string")
        context_filter = frozenset(contexts)
        matches: list[ArtifactLookupMatch] = []
        seen: set[tuple[str, str]] = set()
        for descriptor in self._index.find_by_key(normalized):
            ref_key = (
                descriptor.reference.source_type,
                descriptor.reference.source_id,
            )
            if ref_key in seen:
                continue
            seen.add(ref_key)
            matched = _matched_key(descriptor, normalized)
            if matched is None:
                continue
            project_ids = self._project_ids_for(descriptor.reference)
            if project_id is not None and project_id not in project_ids:
                continue
            if context_filter and not any(
                assignment.context in context_filter
                for assignment in descriptor.contexts
            ):
                continue
            matches.append(
                ArtifactLookupMatch(
                    descriptor=descriptor,
                    document=self._catalog.get(descriptor.reference),
                    matched_key=matched,
                    part=_matching_part(descriptor, matched),
                    project_ids=project_ids,
                )
            )
        return tuple(matches)
