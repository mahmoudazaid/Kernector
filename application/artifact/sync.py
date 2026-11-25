"""Keep the artifact index aligned with sync and upload outcomes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Protocol

from domain.artifact.facts import ArtifactStructuralFacts
from domain.artifact.models import ArtifactDescriptor, ContextAssignment
from domain.artifact.ports import ArtifactDescriptorExtractor, ArtifactIndex
from domain.artifact.rules import ContextClassificationRule
from domain.knowledge import SourceDocument, SourceReference

ClassifyFn = Callable[
    [ArtifactStructuralFacts, Sequence[ContextClassificationRule]],
    tuple[ContextAssignment, ...],
]
FactsForSource = Callable[[SourceDocument], ArtifactStructuralFacts]
ComponentIdsForSource = Callable[[SourceReference], tuple[str, ...]]


class RelationshipRecorder(Protocol):
    """Optional collaborator that records explicit relationships after descriptors."""

    def needs_record(self, source: SourceDocument) -> bool: ...

    def execute(self, source: SourceDocument, *, revision: str) -> None: ...

    def missing_watermark(self, reference: SourceReference) -> bool: ...

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
        self._record_relationships(source, revision=revision)

    def on_skipped(self, reference: SourceReference) -> None:
        """Unchanged sources must not rewrite their descriptor when one exists."""
        del reference

    def record_relationships_if_needed(
        self, source: SourceDocument, *, revision: str
    ) -> None:
        """Retry relationship recording without rewriting descriptors."""
        self._record_relationships(source, revision=revision)

    def needs_relationship_retry(self, reference: SourceReference) -> bool:
        """Return whether a skipped source still needs relationship recording."""
        if self._relationships is None:
            return False
        if not self._relationships.supports(reference):
            return False
        return self._relationships.missing_watermark(reference)

    def on_removed(self, reference: SourceReference) -> None:
        """Delete the descriptor when the catalog source is removed."""
        self._index.remove(reference)

    def _record_relationships(self, source: SourceDocument, *, revision: str) -> None:
        if self._relationships is None:
            return
        try:
            if not self._relationships.needs_record(source):
                return
            self._relationships.execute(source, revision=revision)
        except Exception:
            # Ingest already succeeded; watermark stays unset so the next sync retries.
            return


    def _upsert_with_retry(self, descriptor: ArtifactDescriptor) -> None:
        try:
            self._index.upsert(descriptor)
        except Exception:
            self._index.upsert(descriptor)
