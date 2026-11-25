"""Ports for evidence-backed relationships (#374)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from domain.artifact.models import ArtifactRef
from domain.knowledge import SourceDocument, SourceReference
from domain.relationship.models import (
    EvidenceRef,
    ProviderLink,
    Relationship,
    UnresolvedKey,
)


class RelationshipListFilters(Protocol):
    """Optional filters for listing relationships of an artifact."""

    @property
    def origin(self) -> str | None: ...

    @property
    def verification(self) -> str | None: ...

    @property
    def freshness(self) -> str | None: ...


class RelationshipStore(Protocol):
    """Workspace-bound store of evidence-backed relationships."""

    def upsert_from_evidence(
        self,
        *,
        project_id: str,
        subject: ArtifactRef | UnresolvedKey,
        relation_type: str,
        object: ArtifactRef | UnresolvedKey,
        origin: str,
        verification: str,
        confidence: float,
        freshness: str,
        evidence: EvidenceRef,
        seen_at: str,
        subject_aliases: tuple[str, ...] = (),
        object_aliases: tuple[str, ...] = (),
    ) -> Relationship:
        """Insert or match the canonical edge and merge ``evidence`` atomically.

        ``subject_aliases`` / ``object_aliases`` are external keys that identify
        the same endpoints so unresolved rows merge when either end resolves.
        """

    def mark_stale_for_evidence(
        self, source_ref: SourceReference, revision: str
    ) -> None:
        """Mark edges whose evidence cites ``source_ref`` at other revisions stale."""

    def list_for_artifact(
        self,
        project_id: str,
        ref: ArtifactRef | UnresolvedKey,
        filters: Mapping[str, str] | None = None,
        *,
        aliases: tuple[str, ...] = (),
    ) -> tuple[Relationship, ...]:
        """Return relationships for ``ref`` in ``project_id`` only."""

    def apply_decision(
        self,
        relationship_id: str,
        *,
        verification: str,
        actor: str,
        at: datetime,
    ) -> Relationship:
        """Apply confirm or reject via domain transitions; persist actor and time."""

    def get(self, relationship_id: str) -> Relationship | None:
        """Return a relationship by id, or ``None``."""

    def set_record_watermark(
        self, reference: SourceReference, links_fingerprint: str
    ) -> None:
        """Record that relationships for ``reference`` were written successfully."""

    def get_record_watermark(self, reference: SourceReference) -> str | None:
        """Return the last successful links fingerprint, or ``None``."""


class ExplicitLinkExtractor(Protocol):
    """Extract canonical provider-declared links from a source document."""

    def extract(
        self, document: SourceDocument, raw: Mapping[str, object]
    ) -> tuple[ProviderLink, ...]:
        """Return canonical links; ``raw`` is provider-decoded transport payload."""
