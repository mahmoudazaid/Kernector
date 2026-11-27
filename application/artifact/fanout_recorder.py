"""Fan-out RelationshipRecorder over ordered child recorders (#375)."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from application.artifact.sync import RelationshipRecorder
from application.observability import log_operation
from domain.knowledge import SourceDocument, SourceReference

logger = logging.getLogger(__name__)


class FanOutRelationshipRecorder:
    """Run multiple relationship recorders independently per artifact."""

    def __init__(self, recorders: Sequence[RelationshipRecorder]) -> None:
        self._recorders = tuple(recorders)

    def supports(self, reference: SourceReference) -> bool:
        return any(child.supports(reference) for child in self._recorders)

    def needs_record(self, source: SourceDocument, *, revision: str) -> bool:
        return any(
            child.supports(source.reference)
            and child.needs_record(source, revision=revision)
            for child in self._recorders
        )

    def needs_retry(
        self,
        reference: SourceReference,
        *,
        revision: str,
        links_fingerprint: str | None = None,
    ) -> bool:
        return any(
            child.supports(reference)
            and child.needs_retry(
                reference,
                revision=revision,
                links_fingerprint=links_fingerprint,
            )
            for child in self._recorders
        )

    def missing_watermark(self, reference: SourceReference) -> bool:
        return any(
            child.supports(reference) and child.missing_watermark(reference)
            for child in self._recorders
        )

    def clear_watermark(self, reference: SourceReference) -> None:
        for child in self._recorders:
            child.clear_watermark(reference)

    def resolve_arriving(self, source: SourceDocument) -> None:
        for child in self._recorders:
            if not child.supports(source.reference):
                continue
            try:
                child.resolve_arriving(source)
            except Exception as error:
                log_operation(
                    logger,
                    operation="fanout_resolve_arriving",
                    outcome="error",
                    level=logging.ERROR,
                    error_type=type(error).__name__,
                    child=type(child).__name__,
                    source_id=source.reference.source_id,
                    source_type=source.reference.source_type,
                )

    def execute(self, source: SourceDocument, *, revision: str) -> None:
        for child in self._recorders:
            if not child.supports(source.reference):
                continue
            try:
                if child.needs_record(source, revision=revision):
                    child.execute(source, revision=revision)
                else:
                    child.resolve_arriving(source)
            except Exception as error:
                # Failed child keeps its watermark unchanged for retry.
                log_operation(
                    logger,
                    operation="fanout_execute",
                    outcome="error",
                    level=logging.ERROR,
                    error_type=type(error).__name__,
                    child=type(child).__name__,
                    source_id=source.reference.source_id,
                    source_type=source.reference.source_type,
                )
