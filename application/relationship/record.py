"""Record provider-declared relationships from synced documents (#374)."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from application.relationship.transport import (
    LINKS_FINGERPRINT_EXTRA_KEY,
    PROVIDER_LINKS_EXTRA_KEY,
    TRANSPORT_KEY_PREFIX,
)
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
_WATERMARK_VERSION = "v1"


def links_fingerprint_for(source: SourceDocument) -> str:
    """Return a stable fingerprint of provider link transport on ``source``."""
    payload = source.metadata.extra.get(PROVIDER_LINKS_EXTRA_KEY)
    if isinstance(payload, str) and payload:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    listed = source.metadata.extra.get(LINKS_FINGERPRINT_EXTRA_KEY)
    if isinstance(listed, str) and listed:
        return listed
    parts = [
        f"{key}={value}"
        for key, value in sorted(source.metadata.extra.items())
        if key.startswith(TRANSPORT_KEY_PREFIX)
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def encode_record_watermark(
    links_fingerprint: str,
    revision: str,
    project_ids: tuple[str, ...],
) -> str:
    """Encode fingerprint, revision, and resolved project ids for skip checks."""
    projects = ",".join(sorted(project_ids))
    return f"{_WATERMARK_VERSION}\n{links_fingerprint}\n{revision}\n{projects}"


def parse_record_watermark(
    raw: str,
) -> tuple[str, str, tuple[str, ...]] | None:
    """Parse a watermark; return None when the payload is legacy or corrupt."""
    parts = raw.split("\n", 3)
    if len(parts) != 4 or parts[0] != _WATERMARK_VERSION:
        return None
    _, fingerprint, revision, projects = parts
    project_ids = tuple(item for item in projects.split(",") if item)
    return fingerprint, revision, project_ids


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

    def needs_record(self, source: SourceDocument, *, revision: str) -> bool:
        """Return whether relationships for ``source`` are missing or stale."""
        project_ids = self._project_ids_for(source.reference)
        if not project_ids:
            return False
        expected = encode_record_watermark(
            links_fingerprint_for(source), revision, project_ids
        )
        return self._store.get_record_watermark(source.reference) != expected

    def needs_retry(
        self,
        reference: SourceReference,
        *,
        revision: str,
        links_fingerprint: str | None = None,
    ) -> bool:
        """Return whether a skipped source should re-attempt relationship recording."""
        if not self.supports(reference):
            return False
        project_ids = self._project_ids_for(reference)
        if not project_ids:
            return False
        stored = self._store.get_record_watermark(reference)
        if stored is None:
            return True
        parsed = parse_record_watermark(stored)
        if parsed is None:
            return True
        stored_fingerprint, stored_revision, stored_projects = parsed
        if stored_revision != revision:
            return True
        if stored_projects != tuple(sorted(project_ids)):
            return True
        if (
            links_fingerprint is not None
            and links_fingerprint != stored_fingerprint
        ):
            return True
        return False

    def missing_watermark(self, reference: SourceReference) -> bool:
        """Return whether no successful relationship record exists yet."""
        return self._store.get_record_watermark(reference) is None

    def clear_watermark(self, reference: SourceReference) -> None:
        """Drop the watermark so a returning artifact re-records."""
        self._store.clear_record_watermark(reference)

    def supports(self, reference: SourceReference) -> bool:
        """Return whether an extractor is registered for ``reference``."""
        return str(reference.source_type) in self._extractors

    def execute(self, source: SourceDocument, *, revision: str) -> None:
        """Record links for ``source``; set watermark only on success."""
        extractor = self._extractors.get(str(source.reference.source_type))
        if extractor is None:
            return
        project_ids = self._project_ids_for(source.reference)
        fingerprint = links_fingerprint_for(source)
        seen_at = self._now()
        instance_prefix = _source_instance_prefix(source.reference.source_id)
        if project_ids:
            watermark = encode_record_watermark(fingerprint, revision, project_ids)
            if self._store.get_record_watermark(source.reference) != watermark:
                raw = self._raw_from_document(source)
                links: tuple[ProviderLink, ...] = ()
                if raw is not None:
                    links = extractor.extract(source, raw)
                for project_id in project_ids:
                    for link in links:
                        subject, subject_aliases = self._resolve_endpoint(
                            link.subject_key,
                            instance_prefix=instance_prefix,
                            part_key=link.subject_part_key,
                        )
                        obj, object_aliases = self._resolve_endpoint(
                            link.object_key,
                            instance_prefix=instance_prefix,
                            part_key=link.object_part_key,
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
                self._store.set_record_watermark(source.reference, watermark)
        # Resolve pending unresolved ends across the workspace even when this
        # source has no project association of its own.
        self._resolve_arriving_artifact(source=source, seen_at=seen_at)

    def _resolve_arriving_artifact(
        self,
        *,
        source: SourceDocument,
        seen_at: str,
    ) -> None:
        """Upgrade unresolved endpoints that match this document's keys."""
        descriptor = self._index.get(source.reference)
        if descriptor is None or not descriptor.external_keys:
            return
        arriving_prefix = _source_instance_prefix(source.reference.source_id)
        ref = ArtifactRef(source.reference)
        for key in descriptor.external_keys:
            pending = self._store.list_unresolved_for_key(key)
            for edge in pending:
                evidence = edge.evidence[0]
                evidence_prefix = _source_instance_prefix(evidence.source.source_id)
                if (
                    arriving_prefix
                    and evidence_prefix
                    and arriving_prefix != evidence_prefix
                ):
                    continue
                subject = (
                    ref if self._endpoint_matches(edge.subject, key) else edge.subject
                )
                obj = ref if self._endpoint_matches(edge.object, key) else edge.object
                if subject is edge.subject and obj is edge.object:
                    continue
                self._store.upsert_from_evidence(
                    project_id=edge.project_id,
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
        self,
        key: str,
        *,
        instance_prefix: str,
        part_key: str | None = None,
    ) -> tuple[ArtifactRef | UnresolvedKey, tuple[str, ...]]:
        matches = self._index.find_by_key((key,))
        if not matches:
            return UnresolvedKey(key, part_key=part_key), (key,)
        if instance_prefix:
            preferred = [
                item
                for item in matches
                if item.reference.source_id.startswith(instance_prefix)
            ]
            if not preferred:
                return UnresolvedKey(key, part_key=part_key), (key,)
            chosen = preferred[0]
        else:
            chosen = matches[0]
        # Part-targeted links must not alias every operation on the artifact.
        if part_key is not None:
            aliases = (key,)
        else:
            aliases = tuple(dict.fromkeys((key, *chosen.external_keys)))
        return ArtifactRef(chosen.reference, part_key=part_key), aliases


def _source_instance_prefix(source_id: str) -> str:
    """Return ``{instance}/`` when ``source_id`` looks like ``instance/scope:key``."""
    if "/" not in source_id:
        return ""
    return source_id.split("/", 1)[0] + "/"
