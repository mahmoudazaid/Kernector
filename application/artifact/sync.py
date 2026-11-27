"""Keep the artifact index aligned with sync and upload outcomes."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Protocol

from application.observability import log_operation
from domain.artifact.facts import ArtifactStructuralFacts
from domain.artifact.models import ArtifactDescriptor, ContextAssignment
from domain.artifact.ports import ArtifactDescriptorExtractor, ArtifactIndex
from domain.artifact.rules import ContextClassificationRule
from domain.knowledge import SourceDocument, SourceReference

logger = logging.getLogger(__name__)

ClassifyFn = Callable[
    [ArtifactStructuralFacts, Sequence[ContextClassificationRule]],
    tuple[ContextAssignment, ...],
]
FactsForSource = Callable[[SourceDocument], ArtifactStructuralFacts]
ComponentIdsForSource = Callable[[SourceReference], tuple[str, ...]]


class RelationshipRecorder(Protocol):
    """Optional collaborator that records explicit relationships after descriptors."""

    def needs_record(self, source: SourceDocument, *, revision: str) -> bool: ...

    def execute(self, source: SourceDocument, *, revision: str) -> None: ...

    def needs_retry(
        self,
        reference: SourceReference,
        *,
        revision: str,
        links_fingerprint: str | None = None,
    ) -> bool: ...

    def missing_watermark(self, reference: SourceReference) -> bool: ...

    def clear_watermark(self, reference: SourceReference) -> None: ...

    def resolve_arriving(self, source: SourceDocument) -> None: ...

    def supports(self, reference: SourceReference) -> bool: ...


class ArtifactSyncHook(Protocol):
    """Sync / upload callback surface for descriptor maintenance."""

    def on_ready(self, source: SourceDocument, *, revision: str) -> None: ...

    def on_skipped(self, reference: SourceReference) -> None: ...

    def on_removed(self, reference: SourceReference) -> None: ...

    def has_descriptor(self, reference: SourceReference) -> bool: ...


class SyncArtifactDescriptors:
    """Upsert or remove descriptors after a source becomes ready or is deleted."""

    def __init__(
        self,
        extractor: ArtifactDescriptorExtractor,
        index: ArtifactIndex,
        *,
        classify: ClassifyFn | None = None,
        rules: Sequence[ContextClassificationRule] = (),
        facts_for: FactsForSource | None = None,
        component_ids_for: ComponentIdsForSource | None = None,
        relationships: RelationshipRecorder | None = None,
    ) -> None:
        self._extractor = extractor
        self._index = index
        self._classify = classify
        self._rules = tuple(rules)
        self._facts_for = facts_for
        self._component_ids_for = component_ids_for
        self._relationships = relationships

    def has_descriptor(self, reference: SourceReference) -> bool:
        """Return whether ``reference`` already has a stored descriptor."""
        return self._index.get(reference) is not None

    def on_ready(self, source: SourceDocument, *, revision: str) -> None:
        """Describe ``source`` and upsert, or remove when extraction returns None."""
        descriptor = self._extractor.describe(source)
        if descriptor is None:
            self._index.remove(source.reference)
            self._invalidate_relationship_catalogue()
            self._record_relationships(source, revision=revision)
            return
        descriptor = replace(descriptor, revision=revision)
        if self._classify is not None and self._facts_for is not None:
            contexts = self._classify(self._facts_for(source), self._rules)
            descriptor = replace(descriptor, contexts=contexts)
        if self._component_ids_for is not None:
            descriptor = replace(
                descriptor,
                component_ids=self._component_ids_for(source.reference),
            )
        self._upsert_with_retry(descriptor)
        self._invalidate_relationship_catalogue()
        self._record_relationships(source, revision=revision)

    def on_skipped(self, reference: SourceReference) -> None:
        """Unchanged sources must not rewrite their descriptor when one exists."""
        del reference

    def record_relationships_if_needed(
        self, source: SourceDocument, *, revision: str
    ) -> None:
        """Retry relationship recording without rewriting descriptors."""
        self._record_relationships(source, revision=revision)

    def needs_relationship_retry(
        self,
        reference: SourceReference,
        *,
        revision: str,
        links_fingerprint: str | None = None,
    ) -> bool:
        """Return whether a skipped source still needs relationship recording."""
        if self._relationships is None:
            return False
        if not self._relationships.supports(reference):
            return False
        return self._relationships.needs_retry(
            reference,
            revision=revision,
            links_fingerprint=links_fingerprint,
        )

    def on_removed(self, reference: SourceReference) -> None:
        """Delete the descriptor when the catalog source is removed."""
        self._index.remove(reference)
        self._invalidate_relationship_catalogue()
        if self._relationships is not None:
            self._relationships.clear_watermark(reference)

    def _invalidate_relationship_catalogue(self) -> None:
        if self._relationships is None:
            return
        invalidate = getattr(self._relationships, "invalidate_catalogue", None)
        if callable(invalidate):
            invalidate()

    def _record_relationships(self, source: SourceDocument, *, revision: str) -> None:
        if self._relationships is None:
            return
        try:
            if self._relationships.needs_record(source, revision=revision):
                self._relationships.execute(source, revision=revision)
            else:
                # Arrival resolution must still run when recording is skipped
                # (for example a target with no project association).
                self._relationships.resolve_arriving(source)
        except Exception as error:
            # Ingest already succeeded; watermark stays unchanged so the next
            # sync can retry (revision / project / fingerprint compare).
            log_operation(
                logger,
                operation="record_relationships",
                outcome="error",
                level=logging.ERROR,
                error_type=type(error).__name__,
                source_id=source.reference.source_id,
                source_type=source.reference.source_type,
            )
            return

    def _upsert_with_retry(self, descriptor: ArtifactDescriptor) -> None:
        try:
            self._index.upsert(descriptor)
        except Exception:
            self._index.upsert(descriptor)
