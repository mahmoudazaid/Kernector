"""Uploaded-document composition: ingest, list, preview, replace, delete."""

import logging
from pathlib import Path

from application.contracts import (
    IngestRequest,
    IngestResponse,
)
from application.errors import (
    ApplicationValidationError,
    ConfigurationError,
)
from application.ingest_knowledge import (
    IngestFailure,
    IngestKnowledge,
)
from application.manage_documents import (
    CatalogReadyWriteFailure,
    DocumentManagementError,
    MISSING_UPLOAD_BLOB_ERROR,
    ManageUploadedDocuments,
    PartialCreateFailure,
    PartialDeleteFailure,
    PartialReplaceFailure,
    UnknownDocumentError,
)
from composition import container as _container
from composition.errors import (
    DocumentContentError,
    DocumentOperationError,
    DocumentUploadError,
    MissingUploadContentError,
    PartialDocumentOperationError,
    UnknownUploadedDocumentError,
)
from composition.google_drive.connection import after_google_drive_document_deleted
from domain.errors import DomainValidationError
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    ChunkPage,
    SourceReference,
    SourceType,
    UploadPayload,
)
from domain.ports import (
    DocumentCatalog,
    UploadBlobStore,
    VectorStore,
)
from infrastructure.catalog.errors import CatalogError
from infrastructure.config import Settings
from infrastructure.documents.upload_blob_store import UploadBlobError
from infrastructure.documents.uploaded_files import (
    DocumentExtractionError,
    UnreadableDocumentError,
    UploadedFileExtractor,
    extract_document,
)
from infrastructure.vectorstore.chroma import ChromaStoreError

logger = logging.getLogger(__name__)


def _log_partial_create(error: PartialCreateFailure) -> None:
    """Record that a create half-landed, using only non-sensitive fields.

    Deliberately not ``logger.exception``. The chain behind this failure runs
    through adapter and vendor errors, and their text routinely carries the
    thing that broke: an API key echoed in a 401 body, a request header, an
    absolute catalog path, a slice of the uploaded document. A log file
    outlives the request and is read by more people than the screen was, so
    none of it is written here.

    What survives is what a reader can act on: which operation, that it landed
    partially, and which two exception classes were involved. The values stay
    on the exception — ``ingest_error`` and ``__cause__`` — for a debugger
    attached in-process, and go no further.
    """
    ingest_error = error.ingest_error
    logger.error(
        "operation=document_create outcome=partial_failure "
        "ingest_error=%s catalog_error=%s vector_mutation_started=%s",
        type(ingest_error).__name__,
        type(error.__cause__).__name__,
        getattr(ingest_error, "vector_mutation_started", None),
    )


def _upload_error_from_ingest_failure(
    settings: Settings, error: IngestFailure
) -> DocumentUploadError:
    """Translate an ingest failure into the message the UI should show.

    A store that was built with a different embedding size reports a vendor
    string nobody can act on, so it is replaced with the one instruction that
    fixes it. Every other cause keeps its own text.
    """
    cause = error.__cause__
    if not isinstance(cause, ChromaStoreError):
        return DocumentUploadError(str(error))
    message = str(cause)
    if "dimension" in message.lower():
        message = (
            "The knowledge store was built with a different embedding size "
            "than the current model. Delete the Chroma data directory "
            f"({settings.chroma.persist_path}) and ingest again."
        )
    return DocumentUploadError(message)


def ingest_uploaded_document(
    settings: Settings, path: Path, *, source_id: str
) -> IngestResponse:
    """Extract one uploaded file and ingest it through ``IngestKnowledge``.

    Owns extraction-to-ingestion wiring so presentation never imports the
    document adapter. Temporary-file lifecycle stays in presentation.

    Args:
        settings (Settings): Runtime settings for the ingest factory.
        path (Path): Local file whose suffix is already presentation-validated.
        source_id (str): Caller-supplied source identity.

    Returns:
        IngestResponse: Accepted IDs and chunk count from the use case.

    Raises:
        DocumentUploadError: Extraction failed (blank identity, unsupported
            type, or unreadable content), or the vector store rejected the
            write (for example an embedding-dimension mismatch).
        ConfigurationError: Embedding credentials are missing or unusable.
        ApplicationValidationError: The ingest request is invalid.
    """
    try:
        document = extract_document(path, source_id=source_id)
    except DomainValidationError as error:
        raise DocumentUploadError(str(error)) from error
    except DocumentExtractionError as error:
        raise DocumentUploadError(str(error)) from error

    use_case = _container.build_ingest_knowledge(settings)
    try:
        return use_case.execute(IngestRequest(documents=(document,)))
    except IngestFailure as error:
        raise _upload_error_from_ingest_failure(settings, error) from error


def build_document_extractor() -> UploadedFileExtractor:
    """Build the upload-payload extractor adapter."""
    return UploadedFileExtractor()


def build_manage_uploaded_documents(
    settings: Settings,
    *,
    catalog: DocumentCatalog | None = None,
    blob_store: UploadBlobStore | None = None,
    vector_store: VectorStore | None = None,
) -> ManageUploadedDocuments:
    """Wire create/replace/delete/list for uploaded documents.

    The store and the ingest pipeline are passed as factories the use case calls
    only when it needs them. Catalog listing then costs one SQLite query against
    ``catalog_documents`` — no Chroma client and no embedding credentials —
    which matters because the documents list path should stay cheap on every
    request, and because `list` and `delete` never embed anything.
    Each operation opens at most one store, and list-chunks / mutate paths share
    the same factory, so ingest, delete, and chunk listing cannot drift onto
    different collections.

    Pass ``vector_store`` to reuse a cached DualWrite/Chroma client (hybrid BM25
    stays in sync with uploads; ``DualWrite.list_source_chunks`` forwards to
    Chroma without BM25). When omitted, the first call that needs a store builds
    one via ``build_vector_store``.
    """
    _vector_store = _container.lazy_vector_store(settings, vector_store=vector_store)

    def _ingest() -> IngestKnowledge:
        return _container.build_ingest_knowledge(settings, vector_store=_vector_store())

    return ManageUploadedDocuments(
        catalog=catalog if catalog is not None else _container.build_document_catalog(settings),
        blob_store=(
            blob_store
            if blob_store is not None
            else _container.build_upload_blob_store(settings)
        ),
        extractor=build_document_extractor(),
        ingest_factory=_ingest,
        vector_store_factory=_vector_store,
        max_upload_bytes=settings.max_upload_bytes,
    )


def list_uploaded_documents(
    settings: Settings, *, catalog: DocumentCatalog | None = None
) -> tuple[CatalogDocument, ...]:
    """Return every uploaded-document catalog row."""
    try:
        return tuple(
            build_manage_uploaded_documents(settings, catalog=catalog).list()
        )
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error


def get_uploaded_document_content(
    settings: Settings,
    source_id: str,
    *,
    catalog: DocumentCatalog | None = None,
) -> tuple[CatalogDocument, UploadPayload]:
    """Return catalog metadata and original bytes for an uploaded document."""
    try:
        ops = build_manage_uploaded_documents(settings, catalog=catalog)
        row = ops.get_uploaded_row(source_id)
        if row is None:
            raise UnknownUploadedDocumentError("unknown document")
        # PENDING rows are mid-flight or stranded after a READY write failure;
        # never serve prior-version bytes under the new pending metadata.
        if row.status is CatalogStatus.PENDING:
            raise MissingUploadContentError(
                "no stored content for this document"
            )
        if MISSING_UPLOAD_BLOB_ERROR in (row.error or ""):
            raise MissingUploadContentError(
                "no stored content for this document"
            )
        payload = ops.get_content(row.reference)
    except UploadBlobError as error:
        raise DocumentOperationError(str(error)) from error
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error
    except DocumentManagementError as error:
        raise DocumentOperationError(str(error)) from error
    if payload is None:
        raise MissingUploadContentError("no stored content for this document")
    return row, payload


def create_uploaded_document(
    settings: Settings,
    payload: UploadPayload,
    *,
    catalog: DocumentCatalog | None = None,
    vector_store: VectorStore | None = None,
) -> CatalogDocument:
    """Create a new uploaded document with a system-managed source ID.

    Raises:
        PartialDocumentOperationError: The upload failed and its catalog status
            could not be written, so a stale row may be visible.
        DocumentUploadError: The file could not be extracted or ingested.
        DocumentOperationError: The catalog could not be read or written.
    """
    try:
        return build_manage_uploaded_documents(
            settings, catalog=catalog, vector_store=vector_store
        ).create(payload)
    except UnreadableDocumentError as error:
        raise DocumentContentError(str(error)) from error
    except DocumentExtractionError as error:
        raise DocumentUploadError(str(error)) from error
    except DomainValidationError as error:
        raise DocumentUploadError(str(error)) from error
    except PartialCreateFailure as error:
        _log_partial_create(error)
        raise PartialDocumentOperationError(
            str(error), operation="create"
        ) from error
    except CatalogReadyWriteFailure as error:
        logger.error(
            "operation=document_create outcome=partial_failure "
            "catalog_error=%s source_id=%s",
            type(error.catalog_error).__name__,
            error.source_id,
        )
        raise PartialDocumentOperationError(
            str(error), operation="create"
        ) from error
    except IngestFailure as error:
        raise _upload_error_from_ingest_failure(settings, error) from error
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error
    except DocumentManagementError as error:
        raise DocumentOperationError(str(error)) from error
    except (ApplicationValidationError, ConfigurationError):
        raise
    except Exception as error:
        raise DocumentUploadError(str(error)) from error


def replace_uploaded_document(
    settings: Settings,
    reference: SourceReference,
    payload: UploadPayload,
    *,
    catalog: DocumentCatalog | None = None,
    vector_store: VectorStore | None = None,
) -> CatalogDocument:
    """Replace an existing uploaded document under the same source ID.

    Raises:
        PartialDocumentOperationError: Chunks or the catalog row were left
            mid-replace, so a retry is genuinely required.
        UnknownUploadedDocumentError: ``reference`` is not in the catalog.
        DocumentOperationError: The replace stopped without mutating anything.
        DocumentContentError: The replacement file has no extractable text.
        DocumentUploadError: The replacement file could not be extracted.
    """
    try:
        ops = build_manage_uploaded_documents(
            settings, catalog=catalog, vector_store=vector_store
        )
        return ops.replace(reference, payload)
    except UnknownDocumentError as error:
        raise UnknownUploadedDocumentError(str(error)) from error
    except UnreadableDocumentError as error:
        raise DocumentContentError(str(error)) from error
    except DocumentExtractionError as error:
        raise DocumentUploadError(str(error)) from error
    except DomainValidationError as error:
        raise DocumentUploadError(str(error)) from error
    except PartialReplaceFailure as error:
        raise PartialDocumentOperationError(
            str(error), operation="replace"
        ) from error
    except IngestFailure as error:
        # A failure before the first `delete_source` left the previous version
        # stored and its catalog row restored: nothing for the user to retry.
        if error.vector_mutation_started:
            raise PartialDocumentOperationError(
                str(error), operation="replace"
            ) from error
        raise DocumentOperationError(str(error)) from error
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error
    except DocumentManagementError as error:
        raise DocumentOperationError(str(error)) from error
    except (ApplicationValidationError, ConfigurationError):
        raise
    except Exception as error:
        raise DocumentUploadError(str(error)) from error


def list_uploaded_document_chunks(
    settings: Settings,
    reference: SourceReference,
    *,
    catalog: DocumentCatalog | None = None,
    vector_store: VectorStore | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> ChunkPage:
    """Return stored chunks for a catalogued document, ordered by index.

    Uses the same memoized store as create/replace/delete. Pass ``vector_store``
    to reuse a process-cached client; when omitted, the store opens only after
    the catalog gate via ``build_vector_store``.

    Raises:
        UnknownUploadedDocumentError: ``reference`` is not in the catalog.
        DocumentOperationError: The catalog or vector store could not be read.
    """
    try:
        return build_manage_uploaded_documents(
            settings,
            catalog=catalog,
            vector_store=vector_store,
        ).list_document_chunks(reference, limit=limit, offset=offset)
    except UnknownDocumentError as error:
        raise UnknownUploadedDocumentError(str(error)) from error
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error
    except DocumentManagementError as error:
        raise DocumentOperationError(str(error)) from error
    except (ApplicationValidationError, ConfigurationError):
        raise
    except Exception as error:
        raise DocumentOperationError(str(error)) from error


def delete_uploaded_document(
    settings: Settings,
    reference: SourceReference,
    *,
    catalog: DocumentCatalog | None = None,
    vector_store: VectorStore | None = None,
) -> None:
    """Delete vector chunks then the catalog row for ``reference``.

    Google Drive rows are also removed from the saved Drive file selection so
    the next sync does not bring them back.

    Raises:
        PartialDocumentOperationError: The chunks are gone but the catalog row
            remains, so a retry is genuinely required.
        DocumentOperationError: The delete stopped before removing anything.
    """
    ops = build_manage_uploaded_documents(
        settings, catalog=catalog, vector_store=vector_store
    )
    row = ops.resolve(reference.source_id)
    target = row.reference if row is not None else reference
    try:
        ops.delete(target)
    except PartialDeleteFailure as error:
        raise PartialDocumentOperationError(
            str(error), operation="delete"
        ) from error
    except DocumentManagementError as error:
        raise DocumentOperationError(str(error)) from error
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error
    if (
        row is not None
        and row.reference.source_type == SourceType.GOOGLE_DRIVE
    ):
        after_google_drive_document_deleted(settings, row.reference.source_id)
