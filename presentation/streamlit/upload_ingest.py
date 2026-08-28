"""Upload and document-management helpers for the Streamlit presentation layer.

Owns validation and the mapping of composition results to UI-neutral messages.
Widgets stay in ``app.py``. Temporary-file lifecycle for uploads lives in the
document extractor adapter, not here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from application.errors import ApplicationValidationError, ConfigurationError
from composition import (
    SUPPORTED_UPLOAD_SUFFIXES,
    DocumentOperationError,
    DocumentUploadError,
    PartialDocumentOperationError,
    Settings,
    create_uploaded_document,
    delete_uploaded_document,
    list_uploaded_documents,
    replace_uploaded_document,
)
from domain.errors import DomainValidationError
from domain.knowledge import CatalogDocument, SourceReference, UploadPayload

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UploadIngestResult:
    """UI-neutral outcome of one document-management action.

    Attributes:
        ok (bool): Whether the action succeeded.
        message (str): User-facing success or error text.
        document (CatalogDocument | None): Created or replaced catalog row.
        should_rerun (bool): Whether the UI should call ``st.rerun`` after success.
    """

    ok: bool
    message: str
    document: CatalogDocument | None = None
    should_rerun: bool = False


@dataclass(frozen=True, slots=True)
class DocumentListing:
    """The document list plus the reason it could not be loaded, if any.

    A failed listing is an ordinary page state, not an exception the widget
    layer should have to interpret: the panel still renders, with an error
    banner instead of rows.

    Attributes:
        documents (tuple[CatalogDocument, ...]): Catalog rows, empty on failure.
        error (str | None): User-facing reason the list is unavailable.
    """

    documents: tuple[CatalogDocument, ...] = ()
    error: str | None = None


def load_uploaded_documents(settings: Settings) -> DocumentListing:
    """Return catalog rows for the uploaded-documents list.

    Typed failures carry text the reader can act on. Anything else is logged
    with its traceback and reported generically, so an unexpected error never
    puts server internals on someone's screen.
    """
    try:
        return DocumentListing(documents=tuple(list_uploaded_documents(settings)))
    except (DocumentOperationError, ConfigurationError) as error:
        return DocumentListing(error=f"Could not load uploaded documents: {error}")
    except Exception:
        logger.exception("Unexpected failure listing uploaded documents")
        return DocumentListing(
            error="Could not load uploaded documents. Check the server logs."
        )


def _validate_upload(
    filename: str | None, content: bytes | None
) -> UploadIngestResult | UploadPayload:
    if not filename or content is None:
        return UploadIngestResult(
            ok=False,
            message="Choose a document to upload before submitting.",
        )
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        return UploadIngestResult(
            ok=False,
            message=(
                f"unsupported document type ({suffix!r}); supported types are "
                f"{', '.join(sorted(SUPPORTED_UPLOAD_SUFFIXES))}"
            ),
        )
    return UploadPayload(file_name=filename, content=content)


def create_new_document(
    settings: Settings,
    *,
    filename: str | None,
    content: bytes | None,
) -> UploadIngestResult:
    """Validate and create a new upload with a system-managed source ID."""
    validated = _validate_upload(filename, content)
    if isinstance(validated, UploadIngestResult):
        return validated

    try:
        document = create_uploaded_document(settings, validated)
    except PartialDocumentOperationError:
        # Both the upload and the write that would have recorded it failed, so
        # the detail is a server-side story: log it whole, and tell the reader
        # the only thing they can act on.
        logger.exception("Document create failed and its status was not recorded")
        return UploadIngestResult(
            ok=False,
            message=(
                "Upload failed and its status could not be saved; retry, or "
                "delete any visible pending document."
            ),
        )
    except DocumentUploadError as error:
        return UploadIngestResult(ok=False, message=str(error))
    except DocumentOperationError as error:
        return UploadIngestResult(ok=False, message=str(error))
    except DomainValidationError as error:
        return UploadIngestResult(ok=False, message=str(error))
    except ApplicationValidationError as error:
        return UploadIngestResult(ok=False, message=str(error))
    except ConfigurationError as error:
        return UploadIngestResult(ok=False, message=str(error))
    except Exception:
        logger.exception("Unexpected failure during document create")
        return UploadIngestResult(
            ok=False,
            message="Upload failed unexpectedly. Check the server logs.",
        )
    return UploadIngestResult(
        ok=True,
        message=(
            f"Uploaded {document.file_name} "
            f"({document.chunk_count} chunk(s)). "
            f"Source ID: {document.reference.source_id}"
        ),
        document=document,
        should_rerun=True,
    )


def replace_existing_document(
    settings: Settings,
    *,
    reference: SourceReference,
    filename: str | None,
    content: bytes | None,
) -> UploadIngestResult:
    """Replace content for a selected catalog document under the same ID."""
    validated = _validate_upload(filename, content)
    if isinstance(validated, UploadIngestResult):
        return validated

    try:
        document = replace_uploaded_document(settings, reference, validated)
    except PartialDocumentOperationError as error:
        return UploadIngestResult(
            ok=False,
            message=f"{error} Replacement did not complete; retry Replace or Delete.",
        )
    except DocumentUploadError as error:
        return UploadIngestResult(ok=False, message=str(error))
    except DocumentOperationError as error:
        return UploadIngestResult(ok=False, message=str(error))
    except DomainValidationError as error:
        return UploadIngestResult(ok=False, message=str(error))
    except ApplicationValidationError as error:
        return UploadIngestResult(ok=False, message=str(error))
    except ConfigurationError as error:
        return UploadIngestResult(ok=False, message=str(error))
    except Exception:
        logger.exception("Unexpected failure during document replace")
        return UploadIngestResult(
            ok=False,
            message="Replace failed unexpectedly. Check the server logs.",
        )
    return UploadIngestResult(
        ok=True,
        message=(
            f"Replaced {document.file_name} "
            f"({document.chunk_count} chunk(s)). "
            f"Source ID unchanged: {document.reference.source_id}"
        ),
        document=document,
        should_rerun=True,
    )


def delete_existing_document(
    settings: Settings,
    *,
    reference: SourceReference,
) -> UploadIngestResult:
    """Delete vector chunks and the catalog row for a selected document."""
    try:
        delete_uploaded_document(settings, reference)
    except PartialDocumentOperationError as error:
        return UploadIngestResult(
            ok=False,
            message=f"{error} Retry Delete to finish removing the catalog row.",
        )
    except DocumentOperationError as error:
        return UploadIngestResult(ok=False, message=str(error))
    except ConfigurationError as error:
        return UploadIngestResult(ok=False, message=str(error))
    except Exception:
        logger.exception("Unexpected failure during document delete")
        return UploadIngestResult(
            ok=False,
            message="Delete failed unexpectedly. Check the server logs.",
        )
    return UploadIngestResult(
        ok=True,
        message=f"Deleted document {reference.source_id}.",
        should_rerun=True,
    )
