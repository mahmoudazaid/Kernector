"""Match project references via deterministic matchers (#375)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

from application.artifact.lookup import LookupArtifacts
from application.observability import log_operation
from application.relationship.catalogue import (
    ProjectCatalogueBuilder,
    catalogue_fingerprint,
    limits_fingerprint,
)
from domain.artifact.models import ArtifactRef
from domain.artifact.ports import ArtifactIndex
from domain.knowledge import SourceDocument, SourceReference
from domain.ports import DocumentCatalog
from domain.relationship.matching import (
    DeterministicMatcher,
    MatchDiagnostic,
    MatchLimits,
    MatchMention,
    MatchRequest,
)
from domain.relationship.ports import (
    WATERMARK_KIND_DETERMINISTIC,
    DeterministicEdgeWrite,
    RelationshipStore,
)

logger = logging.getLogger(__name__)

ProjectIdsForSource = Callable[[SourceReference], tuple[str, ...]]

_WATERMARK_VERSION = "det-v1"
_BOUNDS_CODES = frozenset(
    {"content_too_large", "catalogue_overflow", "mention_overflow"}
)


def encode_match_watermark(
    *,
    revision: str,
    project_ids: tuple[str, ...],
    rule_catalogue_version: str,
    limits: MatchLimits,
    catalogue_fp: str,
    bound_state: str = "ok",
) -> str:
    """Encode the mandatory deterministic matching fingerprint."""
    projects = ",".join(sorted(project_ids))
    return (
        f"{_WATERMARK_VERSION}\n{revision}\n{projects}\n"
        f"{rule_catalogue_version}\n{limits_fingerprint(limits)}\n"
        f"{catalogue_fp}\n{bound_state}"
    )


def relations_for_contexts(
    contexts: Sequence[str],
    context_relations: Mapping[str, str],
) -> tuple[str, ...]:
    """Map subject contexts to API-mention relation types (deduped, stable)."""
    found: list[str] = []
    for context in contexts:
        relation = context_relations.get(context)
        if relation is not None and relation not in found:
            found.append(relation)
    return tuple(found)


class MatchProjectReferences:
    """Record deterministic mentions for one ingested/updated artifact."""

    def __init__(
        self,
        store: RelationshipStore,
        index: ArtifactIndex,
        catalog: DocumentCatalog,
        *,
        project_ids_for: ProjectIdsForSource,
        matchers: Sequence[DeterministicMatcher],
        limits: MatchLimits,
        rule_catalogue_version: str,
        context_relations: Mapping[str, str],
        lookup: LookupArtifacts | None = None,
        now: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._index = index
        self._catalog = catalog
        self._project_ids_for = project_ids_for
        self._matchers = tuple(matchers)
        self._limits = limits
        self._rule_catalogue_version = rule_catalogue_version
        self._context_relations = dict(context_relations)
        self._lookup = lookup or LookupArtifacts(
            index, catalog, project_ids_for=project_ids_for
        )
        self._catalogue = ProjectCatalogueBuilder(
            index, project_ids_for=project_ids_for, limits=limits
        )
        self._owned_rule_ids = frozenset(matcher.rule_id for matcher in self._matchers)
        self._now = now or (lambda: datetime.now(UTC).isoformat())

    def supports(self, reference: SourceReference) -> bool:
        """Deterministic matching applies to any source that can carry text."""
        del reference
        return True

    def invalidate_catalogue(self) -> None:
        """Drop cached project catalogues after the artifact index changes."""
        self._catalogue.invalidate()

    def needs_record(self, source: SourceDocument, *, revision: str) -> bool:
        if self._index.get(source.reference) is None:
            return False
        project_ids = self._project_ids_for(source.reference)
        if not project_ids:
            return False
        stored = self._store.get_record_watermark(
            source.reference, kind=WATERMARK_KIND_DETERMINISTIC
        )
        return not self._watermark_current(stored, source.reference, revision, project_ids)

    def needs_retry(
        self,
        reference: SourceReference,
        *,
        revision: str,
        links_fingerprint: str | None = None,
    ) -> bool:
        del links_fingerprint
        if self._index.get(reference) is None:
            return False
        project_ids = self._project_ids_for(reference)
        if not project_ids:
            return False
        stored = self._store.get_record_watermark(
            reference, kind=WATERMARK_KIND_DETERMINISTIC
        )
        return not self._watermark_current(stored, reference, revision, project_ids)

    def missing_watermark(self, reference: SourceReference) -> bool:
        return (
            self._store.get_record_watermark(
                reference, kind=WATERMARK_KIND_DETERMINISTIC
            )
            is None
        )

    def clear_watermark(self, reference: SourceReference) -> None:
        self._store.clear_record_watermark(
            reference, kind=WATERMARK_KIND_DETERMINISTIC
        )

    def resolve_arriving(self, source: SourceDocument) -> None:
        """Deterministic matching does not resolve provider unresolved ends."""
        del source

    def execute(self, source: SourceDocument, *, revision: str) -> None:
        """Match and replace owned deterministic evidence for ``source``."""
        descriptor = self._index.get(source.reference)
        if descriptor is None:
            return
        project_ids = self._project_ids_for(source.reference)
        if not project_ids:
            return

        # Aggregate catalogues across projects the source belongs to.
        # Matching is still per-project when resolving/writing edges.
        diagnostics: list[MatchDiagnostic] = []
        all_mentions: list[tuple[str, MatchMention]] = []
        bound_failure = False
        catalogue_fps: list[str] = []

        for project_id in sorted(project_ids):
            key_catalogue, api_operations, overflow = self._catalogue.build(project_id)
            if overflow is not None:
                bound_failure = True
                diagnostics.append(
                    MatchDiagnostic(
                        code=overflow,
                        rule_id=next(iter(self._owned_rule_ids)),
                        source=source.reference,
                        revision=revision,
                        limit=self._limits.max_catalogue_entries,
                        observed_count=self._limits.max_catalogue_entries + 1,
                    )
                )
                # Keep fingerprint tokens aligned with ``_watermark_current``.
                catalogue_fps.append("overflow")
                continue
            catalogue_fps.append(
                catalogue_fingerprint(key_catalogue, api_operations)
            )
            request = MatchRequest(
                content=source.content,
                source=source.reference,
                revision=revision,
                subject=descriptor,
                key_catalogue=key_catalogue,
                api_operations=api_operations,
                limits=self._limits,
            )
            for matcher in self._matchers:
                outcome = matcher.match(request)
                diagnostics.extend(outcome.diagnostics)
                if any(item.code in _BOUNDS_CODES for item in outcome.diagnostics):
                    bound_failure = True
                    continue
                for mention in outcome.mentions:
                    all_mentions.append((project_id, mention))

        catalogue_fp = hashlib_join(catalogue_fps)
        if bound_failure:
            watermark = encode_match_watermark(
                revision=revision,
                project_ids=project_ids,
                rule_catalogue_version=self._rule_catalogue_version,
                limits=self._limits,
                catalogue_fp=catalogue_fp,
                bound_state="bounds",
            )
            self._store.mark_owned_deterministic_stale(
                source=source.reference,
                owned_rule_ids=self._owned_rule_ids,
                watermark=watermark,
            )
            self._log_diagnostics(source, diagnostics)
            return

        edges = self._resolve_edges(
            source=source,
            revision=revision,
            mentions=all_mentions,
            subject_contexts=tuple(item.context for item in descriptor.contexts),
            diagnostics=diagnostics,
        )
        watermark = encode_match_watermark(
            revision=revision,
            project_ids=project_ids,
            rule_catalogue_version=self._rule_catalogue_version,
            limits=self._limits,
            catalogue_fp=catalogue_fp,
            bound_state="ok",
        )
        self._store.replace_owned_deterministic_evidence(
            source=source.reference,
            revision=revision,
            owned_rule_ids=self._owned_rule_ids,
            edges=edges,
            watermark=watermark,
            seen_at=self._now(),
        )
        self._log_diagnostics(source, diagnostics)

    def _watermark_current(
        self,
        stored: str | None,
        reference: SourceReference,
        revision: str,
        project_ids: tuple[str, ...],
    ) -> bool:
        del reference
        if stored is None:
            return False
        fps: list[str] = []
        for project_id in sorted(project_ids):
            key_catalogue, api_operations, overflow = self._catalogue.build(project_id)
            if overflow is not None:
                fps.append("overflow")
                continue
            fps.append(catalogue_fingerprint(key_catalogue, api_operations))
        catalogue_fp = hashlib_join(fps)
        base = dict(
            revision=revision,
            project_ids=project_ids,
            rule_catalogue_version=self._rule_catalogue_version,
            limits=self._limits,
            catalogue_fp=catalogue_fp,
        )
        return stored in {
            encode_match_watermark(**base, bound_state="ok"),
            encode_match_watermark(**base, bound_state="bounds"),
        }

    def _resolve_edges(
        self,
        *,
        source: SourceDocument,
        revision: str,
        mentions: Sequence[tuple[str, MatchMention]],
        subject_contexts: Sequence[str],
        diagnostics: list[MatchDiagnostic],
    ) -> tuple[DeterministicEdgeWrite, ...]:
        subject = ArtifactRef(source.reference)
        edges: list[DeterministicEdgeWrite] = []
        seen: set[tuple[str, str, str, str]] = set()
        for project_id, mention in mentions:
            relations: tuple[str, ...]
            if mention.relation_type is not None:
                relations = (mention.relation_type,)
            else:
                relations = relations_for_contexts(
                    subject_contexts, self._context_relations
                )
                if not relations:
                    continue
            matches = self._lookup.execute(
                (mention.identity,), project_id=project_id
            )
            if not matches:
                # Unknown keys are ignored; unresolved API ops already diagnosed.
                if mention.rule_id == "api_operation.mention":
                    diagnostics.append(
                        MatchDiagnostic(
                            code="unresolved_operation",
                            rule_id=mention.rule_id,
                            source=source.reference,
                            revision=revision,
                            locator=mention.locator,
                        )
                    )
                continue
            hit = matches[0]
            object_ref = ArtifactRef(
                hit.descriptor.reference,
                part_key=hit.part.part_key if hit.part is not None else None,
            )
            for relation_type in relations:
                dedupe_key = (
                    project_id,
                    relation_type,
                    endpoint_key(subject),
                    endpoint_key(object_ref),
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                from domain.relationship.models import EvidenceRef

                edges.append(
                    DeterministicEdgeWrite(
                        project_id=project_id,
                        subject=subject,
                        relation_type=relation_type,
                        object=object_ref,
                        evidence=EvidenceRef(
                            source=source.reference,
                            revision=revision,
                            locator=mention.locator,
                            extractor_id=mention.rule_id,
                        ),
                        object_aliases=(hit.matched_key,),
                    )
                )
        return tuple(edges)

    def _log_diagnostics(
        self, source: SourceDocument, diagnostics: Sequence[MatchDiagnostic]
    ) -> None:
        for item in diagnostics:
            log_operation(
                logger,
                operation="match_project_references",
                outcome="diagnostic",
                level=logging.INFO,
                code=item.code,
                rule_id=item.rule_id,
                source_id=source.reference.source_id,
                source_type=source.reference.source_type,
                limit=item.limit,
                observed_count=item.observed_count,
            )


def hashlib_join(parts: Sequence[str]) -> str:
    import hashlib

    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def endpoint_key(ref: ArtifactRef) -> str:
    part = ref.part_key or ""
    return f"{ref.reference.source_type}:{ref.reference.source_id}:{part}"
