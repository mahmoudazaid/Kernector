"""Application use cases for uploaded-document create, replace, and delete."""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from application.contracts import IngestRequest, IngestResponse
from application.errors import ApplicationValidationError
from application.ingest_knowledge import IngestFailure, IngestKnowledge
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceDocument,
    SourceReference,
    SourceType,
    UploadPayload,
)
from domain.ports import DocumentCatalog, DocumentExtractor, VectorStore


class DocumentManagementError(RuntimeError):
    """Base error for uploaded-document management failures."""


class PartialCreateFailure(DocumentManagementError):
    """Create failed and the catalog could not record why.

    Two independent failures happened, and reporting only the second would be
    misleading: the catalog write that failed is exactly the one that would
    have recorded the first, so this exception is the only place both survive.

    Attributes:
        ingest_error (BaseException): The failure that stopped the upload. The
            catalog write failure is chained as ``__cause__``.
    """

    def __init__(self, message: str, *, ingest_error: BaseException) -> None:
        super().__init__(message)
        self.ingest_error = ingest_error


class PartialDeleteFailure(DocumentManagementError):
    """Vector chunks were removed but the catalog row could not be deleted."""


class PartialReplaceFailure(DocumentManagementError):
    """Replace recovery could not be persisted; catalog/vector state needs retry."""


class UnknownDocumentError(ApplicationValidationError):
    """Replace or delete targeted a source that is not in the catalog."""


class ManageUploadedDocuments:
    """Owns upload identity, catalog lifecycle, and ordered delete/replace policy.

    The ingest pipeline and the vector store arrive as factories, not instances,
    because ``list`` needs neither and ``delete`` needs no embeddings. Building
    them eagerly would make listing a JSON file fail whenever embedding
    credentials are absent, and would open a vector-store client per call for
    operations that never read one.
    """

    def __init__(
        self,
        *,
        catalog: DocumentCatalog,
        extractor: DocumentExtractor,
        ingest_factory: Callable[[], IngestKnowledge],
        vector_store_factory: Callable[[], VectorStore],
        new_source_id: Callable[[], str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._catalog = catalog
        self._extractor = extractor
        self._ingest_factory = ingest_factory
        self._vector_store_factory = vector_store_factory
        self._new_source_id = new_source_id or (lambda: str(uuid.uuid4()))
        self._now = now or (lambda: datetime.now(UTC))

    def list(self) -> Sequence[CatalogDocument]:
        """Return every uploaded-document catalog row."""
        return self._catalog.all()

    def create(self, payload: UploadPayload) -> CatalogDocument:
        """Allocate a UUID, ingest the upload, and persist catalog status.

        Extraction failures leave no catalog row. An ingest failure that never
        reached the vector store leaves a ``failed`` row; one that may have
        written chunks leaves a ``degraded`` row instead, so the orphaned chunks
        stay visible as state that ``delete`` still has to clear. Either way the
        original error is re-raised unchanged.

        Raises:
            PartialCreateFailure: The ingest failed *and* its status could not
                be written, leaving only the ``pending`` row on disk.
        """
        source_id = self._new_source_id()
        reference = SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)
        if self._catalog.get(reference) is not None:
            raise ApplicationValidationError(
                f"generated source_id {source_id!r} already exists in the catalog"
            )
        document = self._extractor.extract(payload, reference=reference)
        pending = self._pending_row(reference, payload, document)
        self._catalog.upsert(pending)
        try:
            response = self._run_ingest(document)
        except Exception as error:
            self._record_create_failure(pending, error)
            raise
        ready = dataclasses.replace(
            pending,
            status=CatalogStatus.READY,
            chunk_count=response.chunk_count,
        )
        self._catalog.upsert(ready)
        return ready

    def replace(
        self, reference: SourceReference, payload: UploadPayload
    ) -> CatalogDocument:
        """Replace content for an existing catalog source under the same ID."""
        previous = self._catalog.get(reference)
        if previous is None:
            raise UnknownDocumentError(
                f"unknown document {reference.source_type.value}:{reference.source_id}"
            )
        document = self._extractor.extract(payload, reference=reference)
        pending = self._pending_row(reference, payload, document)
        self._catalog.upsert(pending)
        try:
            response = self._run_ingest(document)
        except IngestFailure as error:
            self._recover_replace(previous, pending, error)
            raise
        except ApplicationValidationError:
            # `IngestKnowledge` validates the whole request before its first
            # `delete_source`, so the stored chunks are still the previous
            # version's. Overwriting the ready row here would discard a correct
            # row describing a document that still works.
            self._restore_previous(previous)
            raise
        except Exception as error:
            # Unknown failure outside the typed ingest boundary: assume mutation.
            self._write_degraded(pending, error)
            raise
        ready = dataclasses.replace(
            pending,
            status=CatalogStatus.READY,
            chunk_count=response.chunk_count,
        )
        self._catalog.upsert(ready)
        return ready

    def delete(self, reference: SourceReference) -> None:
        """Delete vector chunks first, then the catalog row.

        Missing chunks or rows are no-ops so retry converges. Catalog failure
        after a successful vector delete raises ``PartialDeleteFailure``.
        """
        try:
            self._vector_store_factory().delete_source(reference)
        except Exception as error:
            raise DocumentManagementError(
                f"could not delete vector chunks for {reference.source_id}: {error}"
            ) from error
        try:
            self._catalog.delete(reference)
        except Exception as error:
            raise PartialDeleteFailure(
                f"chunks removed for {reference.source_id} but catalog row remains: "
                f"{error}"
            ) from error

    def _pending_row(
        self,
        reference: SourceReference,
        payload: UploadPayload,
        document: SourceDocument,
    ) -> CatalogDocument:
        """The one row literal every other status is derived from."""
        return CatalogDocument(
            reference=reference,
            file_name=Path(payload.file_name).name,
            title=document.metadata.title,
            content_format=document.metadata.content_format,
            status=CatalogStatus.PENDING,
            uploaded_at=self._now(),
            chunk_count=0,
            error=None,
        )

    def _run_ingest(self, document: SourceDocument) -> IngestResponse:
        return self._ingest_factory().execute(IngestRequest(documents=(document,)))

    def _record_create_failure(
        self, pending: CatalogDocument, error: BaseException
    ) -> None:
        """Write the outcome status, or report that both writes failed."""
        status = (
            CatalogStatus.DEGRADED
            if _vector_mutation_started(error)
            else CatalogStatus.FAILED
        )
        try:
            self._catalog.upsert(
                dataclasses.replace(
                    pending,
                    status=status,
                    error=_safe_error_summary(error),
                )
            )
        except Exception as catalog_error:
            raise PartialCreateFailure(
                f"upload failed and its {status.value} status could not be "
                f"recorded: {_safe_error_summary(error)}",
                ingest_error=error,
            ) from catalog_error

    def _recover_replace(
        self,
        previous: CatalogDocument,
        pending: CatalogDocument,
        error: IngestFailure,
    ) -> None:
        if not error.vector_mutation_started:
            self._restore_previous(previous)
            return
        self._write_degraded(pending, error)

    def _restore_previous(self, previous: CatalogDocument) -> None:
        try:
            self._catalog.upsert(previous)
        except Exception as catalog_error:
            raise PartialReplaceFailure(
                "replace failed before vector mutation and catalog restore failed; "
                "retry or delete required"
            ) from catalog_error

    def _write_degraded(
        self, pending: CatalogDocument, error: BaseException
    ) -> None:
        degraded = dataclasses.replace(
            pending,
            status=CatalogStatus.DEGRADED,
            error=_safe_error_summary(error),
        )
        try:
            self._catalog.upsert(degraded)
        except Exception as catalog_error:
            raise PartialReplaceFailure(
                "replace did not complete and catalog could not record degraded "
                "status; retry or delete required"
            ) from catalog_error


def _vector_mutation_started(error: BaseException) -> bool:
    """Whether `error` reports that the vector store may already have changed."""
    return isinstance(error, IngestFailure) and error.vector_mutation_started


def _safe_error_summary(error: BaseException) -> str:
    message = str(error).strip() or type(error).__name__
    return message[:500]
