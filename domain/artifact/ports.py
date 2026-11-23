"""Ports for artifact description and indexing (#373)."""

from __future__ import annotations

from typing import Protocol

from domain.artifact.models import ArtifactDescriptor
from domain.knowledge import SourceDocument, SourceReference


class ArtifactDescriptorExtractor(Protocol):
    """Derive an artifact descriptor from an ingested source document."""

    def describe(self, document: SourceDocument) -> ArtifactDescriptor | None:
        """Return a descriptor, or ``None`` when the document is not an artifact."""


class ArtifactIndex(Protocol):
    """Workspace-bound store of artifact descriptors."""

    def upsert(self, descriptor: ArtifactDescriptor) -> None:
        """Insert or replace the descriptor for ``descriptor.reference``."""

    def remove(self, reference: SourceReference) -> None:
        """Delete the descriptor for ``reference`` if present."""

    def find_by_key(self, keys: tuple[str, ...]) -> tuple[ArtifactDescriptor, ...]:
        """Return descriptors whose external keys match any of ``keys``."""

    def list_for_scope(
        self, *, source_type: str | None = None
    ) -> tuple[ArtifactDescriptor, ...]:
        """List descriptors in this workspace, optionally by source type."""

    def get(self, reference: SourceReference) -> ArtifactDescriptor | None:
        """Return the descriptor for ``reference``, or ``None``."""
