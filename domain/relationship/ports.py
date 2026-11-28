"""Ports for evidence-backed relationships (#374, #375)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from domain.artifact.models import ArtifactRef
from domain.knowledge import SourceDocument, SourceReference
from domain.relationship.matching import DeterministicMatcher, MatchRequest, MatchOutcome
from domain.relationship.models import (
    EvidenceRef,
    ProviderLink,
    Relationship,
    UnresolvedKey,
)

# Re-export matcher port for composition imports.
__all__ = (
    "DeterministicEdgeWrite",
    "DeterministicMatcher",
    "ExplicitLinkExtractor",
    "MatchOutcome",
    "MatchRequest",
    "RelationshipListFilters",
    "RelationshipStore",
    "WATERMARK_KIND_DETERMINISTIC",
    "WATERMARK_KIND_PROVIDER_DECLARED",
)

WATERMARK_KIND_PROVIDER_DECLARED = "provider_declared"
WATERMARK_KIND_DETERMINISTIC = "deterministic"


@dataclass(frozen=True, slots=True)
class DeterministicEdgeWrite:
    """One resolved deterministic edge to persist in an owned-evidence replace."""

    project_id: str
    subject: ArtifactRef | UnresolvedKey
    relation_type: str
    object: ArtifactRef | UnresolvedKey
    evidence: EvidenceRef
    subject_aliases: tuple[str, ...] = ()
    object_aliases: tuple[str, ...] = ()


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
        """Mark edges that cite ``source_ref`` with no evidence at ``revision`` stale."""

    def list_for_artifact(
        self,
        project_id: str,
        ref: ArtifactRef | UnresolvedKey,
        filters: Mapping[str, str] | None = None,
        *,
        aliases: tuple[str, ...] = (),
    ) -> tuple[Relationship, ...]:
        """Return relationships for ``ref`` in ``project_id`` only."""

    def list_unresolved_for_key(
        self,
        key: str,
        *,
        part_key: str | None = None,
    ) -> tuple[Relationship, ...]:
        """Return unresolved edges for ``key`` across every project in the workspace."""

    def resolve_endpoints(
        self,
        relationship_id: str,
        *,
        subject: ArtifactRef | UnresolvedKey,
        object: ArtifactRef | UnresolvedKey,
        freshness: str,
    ) -> Relationship:
        """Upgrade endpoints on an existing edge without create-time validation."""

    def apply_decision(
        self,
        relationship_id: str,
        *,
        verification: str,
        actor: str,
        at: datetime,
        expected_version: int,
    ) -> Relationship:
        """Apply confirm or reject via compare-and-swap on ``decision_version``."""

    def get(self, relationship_id: str) -> Relationship | None:
        """Return a relationship by id, or ``None``."""

    def set_record_watermark(
        self,
        reference: SourceReference,
        links_fingerprint: str,
        *,
        kind: str = WATERMARK_KIND_PROVIDER_DECLARED,
    ) -> None:
        """Record that relationships for ``reference`` were written successfully."""

    def get_record_watermark(
        self,
        reference: SourceReference,
        *,
        kind: str = WATERMARK_KIND_PROVIDER_DECLARED,
    ) -> str | None:
        """Return the last successful links fingerprint for ``kind``, or ``None``."""

    def clear_record_watermark(
        self,
        reference: SourceReference,
        *,
        kind: str | None = None,
    ) -> None:
        """Drop watermarks for ``reference``.

        When ``kind`` is ``None``, every kind for the source is cleared.
        """

    def replace_owned_deterministic_evidence(
        self,
        *,
        source: SourceReference,
        revision: str,
        owned_rule_ids: frozenset[str],
        edges: Sequence[DeterministicEdgeWrite],
        watermark: str,
        seen_at: str,
    ) -> None:
        """Atomically replace evidence owned by ``owned_rule_ids`` for ``source``.

        Ownership is the exact registered rule-id set, never a prefix match.
        Matching edges receive new revision evidence; disappeared edges keep
        other evidence or retain last owned evidence and become ``removed``.
        Existing origin and human decision fields are preserved. The
        deterministic watermark is committed in the same transaction.
        """

    def mark_owned_deterministic_stale(
        self,
        *,
        source: SourceReference,
        owned_rule_ids: frozenset[str],
        watermark: str,
    ) -> None:
        """Mark edges with owned evidence from ``source`` stale and set watermark.

        Used for non-destructive bound failures: no evidence rows are removed.
        """


class ExplicitLinkExtractor(Protocol):
    """Extract canonical provider-declared links from a source document."""

    def extract(
        self, document: SourceDocument, raw: Mapping[str, object]
    ) -> tuple[ProviderLink, ...]:
        """Return canonical links; ``raw`` is provider-decoded transport payload."""
