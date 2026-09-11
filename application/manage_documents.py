"""Application use cases for uploaded-document create, replace, and delete."""

from __future__ import annotations

import dataclasses
import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from application.contracts import IngestRequest, IngestResponse
from application.errors import ApplicationValidationError, UploadTooLargeError
from application.ingest_knowledge import IngestFailure, IngestKnowledge
from application.observability import log_operation
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    ChunkPage,
    HUB_SOURCE_TYPES,
    SourceDocument,
    SourceReference,
    SourceType,
    UploadPayload,
)
from domain.ports import (
    DocumentCatalog,
    DocumentExtractor,
    UploadBlobStore,
    VectorStore,
)

logger = logging.getLogger(__name__)

# Catalog ``error`` sentinel when ingest succeeded but the durable original
# could not be written. Status stays READY so operators do not delete a
# searchable document to "fix" a missing preview.
MISSING_UPLOAD_BLOB_ERROR = (
    "document ingested but original bytes could not be stored"
)
_MAX_ERROR_SUMMARY = 500


class DocumentManagementError(RuntimeError):
    """Base error for uploaded-document management failures."""


class PartialCreateFailure(DocumentManagementError):
    """Create failed and the catalog could not record why.

    Two independent failures happened, and reporting only the second would be
    misleading: the catalog write that failed is exactly the one that would
    have recorded the first, so this exception is the only place both survive.

    Both originals stay reachable — ``ingest_error`` as an attribute, the
    catalog write as ``__cause__`` — but neither reaches the message. The
    message is fixed by the class rather than passed in, because this exception
    crosses into presentation: a caller cannot leak an adapter path, a
    credential, or a vendor string through text it has no way to supply. The
    detail is for the server log; the message is for the reader.

    Attributes:
        ingest_error (BaseException): The failure that stopped the upload.
    """

    MESSAGE = (
        "Upload failed and its status could not be saved; retry, or delete any "
        "visible pending document."
    )

    def __init__(self, *, ingest_error: BaseException) -> None:
        super().__init__(self.MESSAGE)
        self.ingest_error = ingest_error


class CatalogReadyWriteFailure(DocumentManagementError):
    """Ingest finished, but the READY catalog write failed.

    Chunks (and usually the blob) are already durable. The catalog still shows
    ``pending``, so the operator must retry or delete the stranded row — this
    is not an ingest failure.

    Attributes:
        catalog_error (BaseException): The catalog adapter failure.
        source_id (str): Document that was ingested.
        source_type (str): Catalog source type for that document.
    """

    MESSAGE = (
        "Document was ingested but its ready status could not be saved; "
        "retry, or delete any visible pending document."
    )

    def __init__(
        self, *, catalog_error: BaseException, reference: SourceReference
    ) -> None:
        super().__init__(self.MESSAGE)
        self.catalog_error = catalog_error
        self.source_id = reference.source_id
        self.source_type = reference.source_type


class VectorDeleteFailure(DocumentManagementError):
    """Vector-store delete failed before the catalog row was touched.

    The message is fixed by the class rather than passed in, because this
    exception crosses into presentation: a caller cannot leak an adapter path,
    a credential, a vendor string, or the caller-supplied document id through
    text it has no way to supply. The detail is for the server log; the
    message is for the reader.

    Attributes:
        source_type (str): Catalog source type that was targeted.
        source_id (str): Caller-supplied identifier that was targeted.
        delete_error (BaseException): The adapter failure that stopped the delete.
    """

    MESSAGE = "Could not delete vector chunks; the catalog row is unchanged."

    def __init__(
        self, *, reference: SourceReference, delete_error: BaseException
    ) -> None:
        super().__init__(self.MESSAGE)
        self.source_type = reference.source_type
        self.source_id = reference.source_id
        self.delete_error = delete_error


class PartialDeleteFailure(DocumentManagementError):
    """Vector chunks were removed but the catalog row could not be deleted.

    Same rationale as :class:`PartialCreateFailure`: this exception crosses
    into presentation, so the message is fixed and the locator plus vendor
    error ride as attributes.

    Attributes:
        source_type (str): Catalog source type that was targeted.
        source_id (str): Caller-supplied identifier whose chunks were removed.
        delete_error (BaseException): The catalog failure that left the row.
    """

    MESSAGE = (
        "Chunks were removed but the catalog row remains; retry the delete."
    )

    def __init__(
        self, *, reference: SourceReference, delete_error: BaseException
    ) -> None:
        super().__init__(self.MESSAGE)
        self.source_type = reference.source_type
        self.source_id = reference.source_id
        self.delete_error = delete_error


class PartialReplaceFailure(DocumentManagementError):
    """Replace recovery could not be persisted; catalog/vector state needs retry."""


class UnknownDocumentError(ApplicationValidationError):
    """Replace or delete targeted a source that is not in the catalog.

    The locator is caller-supplied, so it stays off the message and rides on
    the exception instead — reachable from a log record or ``__cause__``
    without being interpolated into text that travels up the chain.

    Attributes:
        source_type (str): Catalog source type that was searched.
        source_id (str): Caller-supplied identifier that was not found.
    """

    def __init__(self, *, reference: SourceReference) -> None:
        super().__init__("unknown document")
        self.source_type = reference.source_type
        self.source_id = reference.source_id


class SourceIdCollisionError(ApplicationValidationError):
    """A freshly generated ``source_id`` already exists in the catalog.

    Means the injected ``new_source_id`` factory is repeating, so the colliding
    id is the one thing an operator needs. It is generated rather than
    caller-supplied, but the message stays uniform with the rest of the layer;
    the id is carried as an attribute.

    Attributes:
        source_id (str): The generated identifier that collided.
    """

    def __init__(self, *, source_id: str) -> None:
        super().__init__("generated source_id already exists in the catalog")
        self.source_id = source_id


class ManageUploadedDocuments:
    """Owns upload identity, catalog lifecycle, and ordered delete/replace policy.

    The ingest pipeline and the vector store arrive as factories, not instances,
    because ``list`` needs neither and ``delete`` needs no embeddings. Building
    them eagerly would make listing a JSON file fail whenever embedding
    credentials are absent, and would open a vector-store client per call for
    operations that never read one.
    """

    _HUB_SOURCE_TYPES = HUB_SOURCE_TYPES

    def __init__(
        self,
        *,
        catalog: DocumentCatalog,
        blob_store: UploadBlobStore,
        extractor: DocumentExtractor,
        ingest_factory: Callable[[], IngestKnowledge],
        vector_store_factory: Callable[[], VectorStore],
        new_source_id: Callable[[], str] | None = None,
        now: Callable[[], datetime] | None = None,
        max_upload_bytes: int,
    ) -> None:
        self._catalog = catalog
        self._blob_store = blob_store
        self._extractor = extractor
        self._ingest_factory = ingest_factory
        self._vector_store_factory = vector_store_factory
        self._new_source_id = new_source_id or (lambda: str(uuid.uuid4()))
        self._now = now or (lambda: datetime.now(UTC))
        self._max_upload_bytes = max_upload_bytes

    def list(self) -> Sequence[CatalogDocument]:
        """Return catalog rows shown in the shared documents hub."""
        return tuple(
            row
            for row in self._catalog.all()
            if row.reference.source_type in self._HUB_SOURCE_TYPES
        )

    def _unknown(
        self, reference: SourceReference, *, operation: str
    ) -> UnknownDocumentError:
        error = UnknownDocumentError(reference=reference)
        log_operation(
            logger,
            operation=operation,
            outcome="error",
            level=logging.ERROR,
            error_type=type(error).__name__,
            source_id=error.source_id,
            source_type=error.source_type,
        )
        return error

    def list_document_chunks(
        self,
        reference: SourceReference,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> ChunkPage:
        """Return stored chunks for a catalogued source, ordered by index.

        Looks up ``reference`` in the catalog first. An unknown reference raises
        ``UnknownDocumentError`` without opening the vector store. Non-hub
        ``source_type`` values are treated as unknown. A known row with no
        stored chunks returns an empty page. Optional ``limit``/``offset``
        are forwarded to the vector store (no post-fetch slice).
        """
        if (
            reference.source_type not in self._HUB_SOURCE_TYPES
            or self._catalog.get(reference) is None
        ):
            raise self._unknown(reference, operation="list_chunks")
        return self._vector_store_factory().list_source_chunks(
            reference, limit=limit, offset=offset
        )

    def create(self, payload: UploadPayload) -> CatalogDocument:
        """Allocate a UUID, ingest the upload, and persist catalog status.

        Extraction failures leave no catalog row. An ingest failure that never
        reached the vector store leaves a ``failed`` row; one that may have
        written chunks leaves a ``degraded`` row instead, so the orphaned chunks
        stay visible as state that ``delete`` still has to clear. Either way the
        original error is re-raised unchanged.

        Raises:
            UploadTooLargeError: ``payload.content`` exceeds
                ``max_upload_bytes``.
            SourceIdCollisionError: The generated ``source_id`` is already in
                the catalog, so the injected id factory is repeating.
            PartialCreateFailure: The ingest failed *and* its status could not
                be written, leaving only the ``pending`` row on disk.
            CatalogReadyWriteFailure: Ingest finished but the READY catalog
                write failed, leaving a stranded ``pending`` row.
        """
        self._assert_upload_size(payload)
        source_id = self._new_source_id()
        reference = SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)
        if self._catalog.get(reference) is not None:
            collision = SourceIdCollisionError(source_id=source_id)
            log_operation(
                logger,
                operation="create",
                outcome="error",
                level=logging.ERROR,
                error_type=type(collision).__name__,
                source_id=collision.source_id,
            )
            raise collision
        document = self._extractor.extract(payload, reference=reference)
        pending = self._pending_row(reference, payload, document)
        self._catalog.upsert(pending)
        try:
            response = self._run_ingest(document)
        except Exception as error:
            self._record_create_failure(pending, payload, error)
            raise
        ready = dataclasses.replace(
            pending,
            status=CatalogStatus.READY,
            chunk_count=response.chunk_count,
        )
        return self._finalize_ready(ready, payload, operation="create")

    def replace(
        self, reference: SourceReference, payload: UploadPayload
    ) -> CatalogDocument:
        """Replace content for an existing catalog source under the same ID."""
        previous = self._catalog.get(reference)
        if previous is None:
            raise self._unknown(reference, operation="replace")
        self._assert_upload_size(payload)
        document = self._extractor.extract(payload, reference=reference)
        pending = self._pending_row(reference, payload, document)
        self._catalog.upsert(pending)
        try:
            response = self._run_ingest(document)
        except IngestFailure as error:
            self._recover_replace(previous, pending, payload, error)
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
            self._write_degraded(pending, payload, error)
            raise
        ready = dataclasses.replace(
            pending,
            status=CatalogStatus.READY,
            chunk_count=response.chunk_count,
        )
        return self._finalize_ready(ready, payload, operation="replace")

    def resolve(self, source_id: str) -> CatalogDocument | None:
        """Return the hub catalog row for ``source_id``, if one exists."""
        for row in self._catalog.all():
            if (
                row.reference.source_id == source_id
                and row.reference.source_type in self._HUB_SOURCE_TYPES
            ):
                return row
        return None

    def get_uploaded_row(self, source_id: str) -> CatalogDocument | None:
        """Return the upload catalog row for ``source_id`` via a keyed lookup."""
        return self._catalog.get(
            SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)
        )

    def get_content(
        self, reference: SourceReference
    ) -> UploadPayload | None:
        """Return original upload bytes for an uploaded-document reference."""
        if reference.source_type != SourceType.KNOWLEDGE_DOCUMENT:
            return None
        return self._blob_store.get(reference)

    def delete(self, reference: SourceReference) -> None:
        """Delete vector chunks, then the blob (uploads only), then the catalog row.

        Missing chunks or rows are no-ops so retry converges. Catalog failure
        after a successful vector delete raises ``PartialDeleteFailure``.
        Blob unlink failures also raise ``PartialDeleteFailure`` so the catalog
        row remains and a retry can reclaim the orphan. Google Drive rows skip
        the blob store entirely.
        """
        try:
            self._vector_store_factory().delete_source(reference)
        except Exception as error:
            failure = VectorDeleteFailure(
                reference=reference, delete_error=error
            )
            log_operation(
                logger,
                operation="delete",
                outcome="error",
                level=logging.ERROR,
                error_type=type(failure).__name__,
                source_id=failure.source_id,
                source_type=failure.source_type,
            )
            raise failure from error
        if reference.source_type == SourceType.KNOWLEDGE_DOCUMENT:
            try:
                self._blob_store.delete(reference)
            except Exception as error:
                failure = PartialDeleteFailure(
                    reference=reference, delete_error=error
                )
                log_operation(
                    logger,
                    operation="delete",
                    outcome="error",
                    level=logging.ERROR,
                    error_type=type(failure).__name__,
                    source_id=failure.source_id,
                    source_type=failure.source_type,
                )
                raise failure from error
        try:
            self._catalog.delete(reference)
        except Exception as error:
            failure = PartialDeleteFailure(
                reference=reference, delete_error=error
            )
            log_operation(
                logger,
                operation="delete",
                outcome="error",
                level=logging.ERROR,
                error_type=type(failure).__name__,
                source_id=failure.source_id,
                source_type=failure.source_type,
            )
            raise failure from error

    def _finalize_ready(
        self,
        ready: CatalogDocument,
        payload: UploadPayload,
        *,
        operation: str,
    ) -> CatalogDocument:
        """Persist the original bytes, then write the READY catalog row.

        Blob-before-READY keeps ``status == ready`` aligned with durable
        originals when the put succeeds. A put failure still yields READY
        (searchable chunks) with ``MISSING_UPLOAD_BLOB_ERROR`` so the UI can
        distinguish "preview unavailable" from orphaned-chunk ``DEGRADED``.
        Previous blob bytes are left in place on a transient put failure so a
        retry can recover them; content serving refuses ``pending`` rows and
        rows that carry the missing-blob sentinel so stale bytes are never
        returned under the new name or media type.
        """
        blob_ok = self._try_put_blob(
            ready.reference, payload, operation=operation
        )
        if not blob_ok:
            ready = dataclasses.replace(
                ready, error=MISSING_UPLOAD_BLOB_ERROR
            )
        try:
            self._catalog.upsert(ready)
        except Exception as catalog_error:
            if operation == "replace":
                raise PartialReplaceFailure(
                    "document was ingested but catalog could not record ready "
                    "status; retry or delete required"
                ) from catalog_error
            raise CatalogReadyWriteFailure(
                catalog_error=catalog_error, reference=ready.reference
            ) from catalog_error
        return ready

    def _try_put_blob(
        self,
        reference: SourceReference,
        payload: UploadPayload,
        *,
        operation: str,
    ) -> bool:
        """Persist ``payload``; log and return False on failure."""
        try:
            self._blob_store.put(reference, payload)
            return True
        except Exception as error:
            log_operation(
                logger,
                operation=operation,
                outcome="error",
                level=logging.WARNING,
                error_type=type(error).__name__,
                source_id=reference.source_id,
                source_type=reference.source_type,
            )
            return False

    def _assert_upload_size(self, payload: UploadPayload) -> None:
        size = len(payload.content)
        if size > self._max_upload_bytes:
            raise UploadTooLargeError.for_file(
                limit_bytes=self._max_upload_bytes,
                actual_bytes=size,
            )

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
        self,
        pending: CatalogDocument,
        payload: UploadPayload,
        error: BaseException,
    ) -> None:
        """Write the outcome status, or report that both writes failed.

        The summary stored in the row's ``error`` field is a catalog
        diagnostic, read back only by whoever is already looking at that
        document. It is deliberately not what ``PartialCreateFailure`` says.
        Blob put runs before the outcome upsert so a missing original is
        recorded in the same write as FAILED/DEGRADED (sentinel cannot be lost
        by a second annotate upsert). Annotation write failures are logged and
        the original ingest error still propagates from ``create``.
        """
        status = (
            CatalogStatus.DEGRADED
            if _vector_mutation_started(error)
            else CatalogStatus.FAILED
        )
        summary = _safe_error_summary(error)
        if not self._try_put_blob(
            pending.reference, payload, operation="create"
        ):
            summary = _with_missing_blob_note(summary)
        failed = dataclasses.replace(
            pending,
            status=status,
            error=summary,
        )
        try:
            self._catalog.upsert(failed)
        except Exception as catalog_error:
            raise PartialCreateFailure(ingest_error=error) from catalog_error

    def _recover_replace(
        self,
        previous: CatalogDocument,
        pending: CatalogDocument,
        payload: UploadPayload,
        error: IngestFailure,
    ) -> None:
        if not error.vector_mutation_started:
            self._restore_previous(previous)
            return
        self._write_degraded(pending, payload, error)

    def _restore_previous(self, previous: CatalogDocument) -> None:
        try:
            self._catalog.upsert(previous)
        except Exception as catalog_error:
            raise PartialReplaceFailure(
                "replace failed before vector mutation and catalog restore failed; "
                "retry or delete required"
            ) from catalog_error

    def _write_degraded(
        self,
        pending: CatalogDocument,
        payload: UploadPayload,
        error: BaseException,
    ) -> None:
        """Record DEGRADED after a mutation may have started.

        Blob put runs before the catalog write so a missing original is folded
        into the same DEGRADED row (sentinel cannot be lost by a follow-up
        annotate). Prior blob bytes are left in place for recovery; content
        serving refuses the sentinel and ``pending`` rows.
        """
        summary = _safe_error_summary(error)
        if not self._try_put_blob(
            pending.reference, payload, operation="replace"
        ):
            summary = _with_missing_blob_note(summary)
        degraded = dataclasses.replace(
            pending,
            status=CatalogStatus.DEGRADED,
            error=summary,
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
    return message[:_MAX_ERROR_SUMMARY]


def _with_missing_blob_note(existing: str | None) -> str:
    """Append the missing-blob sentinel without dropping the ingest summary."""
    if not existing:
        return MISSING_UPLOAD_BLOB_ERROR
    if MISSING_UPLOAD_BLOB_ERROR in existing:
        return existing
    head = existing[
        : _MAX_ERROR_SUMMARY - len(MISSING_UPLOAD_BLOB_ERROR) - 2
    ]
    return f"{head}; {MISSING_UPLOAD_BLOB_ERROR}"
