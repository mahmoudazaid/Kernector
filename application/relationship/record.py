"""Record provider-declared relationships from synced documents (#374)."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from application.relationship.transport import TRANSPORT_KEY_PREFIX
from domain.artifact.models import ArtifactRef
from domain.artifact.ports import ArtifactIndex
from domain.knowledge import SourceDocument, SourceReference
from domain.relationship.models import (
    FRESHNESS_CURRENT,
    ORIGIN_PROVIDER_DECLARED,
    VERIFICATION_VERIFIED,
    EvidenceRef,
    ProviderLink,
    UnresolvedKey,
)
from domain.relationship.ports import ExplicitLinkExtractor, RelationshipStore

logger = logging.getLogger(__name__)

ProjectIdsForSource = Callable[[SourceReference], tuple[str, ...]]
RawFromDocument = Callable[[SourceDocument], Mapping[str, object] | None]
DEFAULT_EXTRACTOR_ID = "explicit_links"


def links_fingerprint_for(source: SourceDocument) -> str:
    """Return a stable fingerprint of namespaced transport link payloads."""
    parts = [
        f"{key}={value}"
        for key, value in sorted(source.metadata.extra.items())
        if key.startswith(TRANSPORT_KEY_PREFIX)
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


class RecordExplicitRelationships:
    """Upsert canonical provider-declared edges for one ready source document."""

    def __init__(
        self,
        store: RelationshipStore,
        index: ArtifactIndex,
        *,
        project_ids_for: ProjectIdsForSource,
        extractors: Mapping[str, ExplicitLinkExtractor],
        raw_from_document: RawFromDocument,
        extractor_id: str = DEFAULT_EXTRACTOR_ID,
        now: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._index = index
        self._project_ids_for = project_ids_for
        self._extractors = dict(extractors)
        self._raw_from_document = raw_from_document
        self._extractor_id = extractor_id
        self._now = now or (lambda: datetime.now(UTC).isoformat())

    def needs_record(self, source: SourceDocument) -> bool:
        """Return whether relationships for ``source`` are missing or stale."""
        fingerprint = links_fingerprint_for(source)
        return self._store.get_record_watermark(source.reference) != fingerprint

    def missing_watermark(self, reference: SourceReference) -> bool:
        """Return whether no successful relationship record exists yet."""
        return self._store.get_record_watermark(reference) is None

    def supports(self, reference: SourceReference) -> bool:
        """Return whether an extractor is registered for ``reference``."""
        return str(reference.source_type) in self._extractors

    def execute(self, source: SourceDocument, *, revision: str) -> None:
        """Record links for ``source``; set watermark only on success."""
        extractor = self._extractors.get(str(source.reference.source_type))
        if extractor is None:
            return
        fingerprint = links_fingerprint_for(source)
        if self._store.get_record_watermark(source.reference) == fingerprint:
            return
        project_ids = self._project_ids_for(source.reference)
        if not project_ids:
            self._store.set_record_watermark(source.reference, fingerprint)
            return
        raw = self._raw_from_document(source)
        links: tuple[ProviderLink, ...] = ()
        if raw is not None:
            links = extractor.extract(source, raw)
        seen_at = self._now()
        instance_prefix = _source_instance_prefix(source.reference.source_id)
        for project_id in project_ids:
            for link in links:
                subject, subject_aliases = self._resolve_endpoint(
                    link.subject_key, instance_prefix=instance_prefix
                )
                obj, object_aliases = self._resolve_endpoint(
                    link.object_key, instance_prefix=instance_prefix
                )
                evidence = EvidenceRef(
                    source=source.reference,
                    revision=revision,
                    locator=link.locator,
                    extractor_id=self._extractor_id,
                )
                self._store.upsert_from_evidence(
                    project_id=project_id,
                    subject=subject,
                    relation_type=link.relation_type,
                    object=obj,
                    origin=ORIGIN_PROVIDER_DECLARED,
                    verification=VERIFICATION_VERIFIED,
                    confidence=1.0,
                    freshness=FRESHNESS_CURRENT,
                    evidence=evidence,
                    seen_at=seen_at,
                    subject_aliases=subject_aliases,
                    object_aliases=object_aliases,
                )
            self._resolve_arriving_artifact(
                project_id=project_id,
                source=source,
                seen_at=seen_at,
            )
        self._store.set_record_watermark(source.reference, fingerprint)

    def _resolve_arriving_artifact(
        self,
        *,
        project_id: str,
        source: SourceDocument,
        seen_at: str,
    ) -> None:
        """Upgrade unresolved endpoints that match this document's keys."""
        descriptor = self._index.get(source.reference)
        if descriptor is None or not descriptor.external_keys:
            return
        ref = ArtifactRef(source.reference)
        for key in descriptor.external_keys:
            pending = self._store.list_for_artifact(
                project_id,
                UnresolvedKey(key),
                aliases=(key,),
            )
            for edge in pending:
                subject = (
                    ref if self._endpoint_matches(edge.subject, key) else edge.subject
                )
                obj = ref if self._endpoint_matches(edge.object, key) else edge.object
                if subject is edge.subject and obj is edge.object:
                    continue
                evidence = edge.evidence[0]
                self._store.upsert_from_evidence(
                    project_id=project_id,
                    subject=subject,
                    relation_type=edge.relation_type,
                    object=obj,
                    origin=edge.origin,
                    verification=edge.verification,
                    confidence=edge.confidence,
                    freshness=FRESHNESS_CURRENT,
                    evidence=EvidenceRef(
                        source=evidence.source,
                        revision=evidence.revision,
                        locator=evidence.locator,
                        extractor_id=evidence.extractor_id,
                    ),
                    seen_at=seen_at,
                    subject_aliases=(key,) if isinstance(subject, ArtifactRef) else (),
                    object_aliases=(key,) if isinstance(obj, ArtifactRef) else (),
                )

    def _endpoint_matches(
        self, endpoint: ArtifactRef | UnresolvedKey, key: str
    ) -> bool:
        return isinstance(endpoint, UnresolvedKey) and endpoint.key == key

    def _resolve_endpoint(
        self, key: str, *, instance_prefix: str
    ) -> tuple[ArtifactRef | UnresolvedKey, tuple[str, ...]]:
        matches = self._index.find_by_key((key,))
        if not matches:
            return UnresolvedKey(key), (key,)
        preferred = [
            item
            for item in matches
            if instance_prefix and item.reference.source_id.startswith(instance_prefix)
        ]
        chosen = preferred[0] if preferred else matches[0]
        aliases = tuple(dict.fromkeys((key, *chosen.external_keys)))
        return ArtifactRef(chosen.reference), aliases


def _source_instance_prefix(source_id: str) -> str:
    """Return ``{instance}/`` when ``source_id`` looks like ``instance/scope:key``."""
    if "/" not in source_id:
        return ""
    return source_id.split("/", 1)[0] + "/"
