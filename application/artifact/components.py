"""Refresh descriptor component_ids without re-extraction (#373)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from domain.artifact.ports import ArtifactIndex
from domain.knowledge import SourceReference

ComponentIdsForSource = Callable[[SourceReference], tuple[str, ...]]


class RefreshArtifactComponents:
    """Recompute stored ``component_ids`` from current membership only."""

    def __init__(
        self,
        index: ArtifactIndex,
        *,
        component_ids_for: ComponentIdsForSource,
    ) -> None:
        self._index = index
        self._component_ids_for = component_ids_for

    def execute(self, reference: SourceReference) -> None:
        descriptor = self._index.get(reference)
        if descriptor is None:
            return
        component_ids = self._component_ids_for(reference)
        if component_ids == descriptor.component_ids:
            return
        self._index.upsert(replace(descriptor, component_ids=component_ids))
