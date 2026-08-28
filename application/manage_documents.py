"""Application use cases for uploaded-document create, replace, and delete."""

from __future__ import annotations

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
    SourceReference,
    SourceType,
    UploadPayload,
)
from domain.ports import DocumentCatalog, DocumentExtractor, VectorStore


class DocumentManagementError(RuntimeError):
    """Base error for uploaded-document management failures."""


class PartialDeleteFailure(DocumentManagementError):
    """Vector chunks were removed but the catalog row could not be deleted."""


class PartialReplaceFailure(DocumentManagementError):
    """Replace recovery could not be persisted; catalog/vector state needs retry."""


class UnknownDocumentError(ApplicationValidationError):
    """Replace or delete targeted a source that is not in the catalog."""


class ManageUploadedDocuments:
    """Owns upload identity, catalog lifecycle, and ordered delete/replace policy."""

    def __init__(
        self,
        *,
        catalog: DocumentCatalog,
        extractor: DocumentExtractor,
        ingest: IngestKnowledge,
        vector_store: VectorStore,
        new_source_id: Callable[[], str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._catalog = catalog
        self._extractor = extractor
        self._ingest = ingest
        self._vector_store = vector_store
        self._new_source_id = new_source_id or (lambda: str(uuid.uuid4()))
        self._now = now or (lambda: datetime.now(UTC))

    def list(self) -> Sequence[CatalogDocument]:
        """Return every uploaded-document catalog row."""
        return self._catalog.all()

    def create(self, payload: UploadPayload) -> CatalogDocument:
        """Allocate a UUID, ingest the upload, and persist catalog status.

        Extraction failures leave no catalog row. Ingest failures leave a
        ``failed`` row and re-raise the original error.
        """
        source_id = self._new_source_id()
        reference = SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)
        if self._catalog.get(reference) is not None:
            raise ApplicationValidationError(
                f"generated source_id {source_id!r} already exists in the catalog"
            )
        document = self._extractor.extract(payload, reference=reference)
        file_name = Path(payload.file_name).name
        pending = CatalogDocument(
            reference=reference,
            file_name=file_name,
            title=document.metadata.title,
            content_format=document.metadata.content_format,
            status=CatalogStatus.PENDING,
            uploaded_at=self._now(),
            chunk_count=0,
            error=None,
        )
        self._catalog.upsert(pending)
        try:
            response = self._run_ingest(document)
        except Exception as error:
            failed = CatalogDocument(
                reference=reference,
                file_name=file_name,
                title=document.metadata.title,
                content_format=document.metadata.content_format,
                status=CatalogStatus.FAILED,
                uploaded_at=pending.uploaded_at,
                chunk_count=0,
                error=_safe_error_summary(error),
            )
            self._catalog.upsert(failed)
            if isinstance(error, IngestFailure) and error.__cause__ is not None:
                raise error.__cause__ from error
            raise
        ready = CatalogDocument(
            reference=reference,
            file_name=file_name,
            title=document.metadata.title,
            content_format=document.metadata.content_format,
            status=CatalogStatus.READY,
            uploaded_at=pending.uploaded_at,
            chunk_count=response.chunk_count,
            error=None,
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
        file_name = Path(payload.file_name).name
        pending = CatalogDocument(
            reference=reference,
            file_name=file_name,
            title=document.metadata.title,
            content_format=document.metadata.content_format,
            status=CatalogStatus.PENDING,
            uploaded_at=self._now(),
            chunk_count=0,
            error=None,
        )
        self._catalog.upsert(pending)
        try:
            response = self._run_ingest(document)
        except IngestFailure as error:
            self._recover_replace(previous, pending, error)
            raise
        except Exception as error:
            # Unknown failure before a typed ingest boundary: treat as possible mutation.
            self._write_degraded(pending, error)
            raise
        ready = CatalogDocument(
            reference=reference,
            file_name=file_name,
            title=document.metadata.title,
            content_format=document.metadata.content_format,
            status=CatalogStatus.READY,
            uploaded_at=pending.uploaded_at,
            chunk_count=response.chunk_count,
            error=None,
        )
        self._catalog.upsert(ready)
        return ready

    def delete(self, reference: SourceReference) -> None:
        """Delete vector chunks first, then the catalog row.

        Missing chunks or rows are no-ops so retry converges. Catalog failure
        after a successful vector delete raises ``PartialDeleteFailure``.
        """
        try:
            self._vector_store.delete_source(reference)
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

    def _run_ingest(self, document) -> IngestResponse:  # type: ignore[no-untyped-def]
        return self._ingest.execute(IngestRequest(documents=(document,)))

    def _recover_replace(
        self,
        previous: CatalogDocument,
        pending: CatalogDocument,
        error: IngestFailure,
    ) -> None:
        if not error.vector_mutation_started:
            try:
                self._catalog.upsert(previous)
            except Exception as catalog_error:
                raise PartialReplaceFailure(
                    "replace failed before vector mutation and catalog restore failed; "
                    "retry or delete required"
                ) from catalog_error
            return
        self._write_degraded(pending, error)

    def _write_degraded(
        self, pending: CatalogDocument, error: BaseException
    ) -> None:
        degraded = CatalogDocument(
            reference=pending.reference,
            file_name=pending.file_name,
            title=pending.title,
            content_format=pending.content_format,
            status=CatalogStatus.DEGRADED,
            uploaded_at=pending.uploaded_at,
            chunk_count=0,
            error=_safe_error_summary(error),
        )
        try:
            self._catalog.upsert(degraded)
        except Exception as catalog_error:
            raise PartialReplaceFailure(
                "replace did not complete and catalog could not record degraded "
                "status; retry or delete required"
            ) from catalog_error


def _safe_error_summary(error: BaseException) -> str:
    message = str(error).strip() or type(error).__name__
    return message[:500]
