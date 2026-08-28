"""Upload and document-management helpers for the Streamlit presentation layer.

Owns validation, the in-flight guard, and mapping of composition results to
UI-neutral messages. Widgets stay in ``app.py``. Temporary-file lifecycle for
uploads lives in the document extractor adapter, not here.
"""

from __future__ import annotations

import logging
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from application.errors import ApplicationValidationError, ConfigurationError
from composition import (
    SUPPORTED_UPLOAD_SUFFIXES,
    DocumentOperationError,
    DocumentUploadError,
    Settings,
    create_uploaded_document,
    delete_uploaded_document,
    list_uploaded_documents,
    replace_uploaded_document,
)
from domain.errors import DomainValidationError
from domain.knowledge import CatalogDocument, SourceReference, UploadPayload

logger = logging.getLogger(__name__)

_IN_PROGRESS_KEY = "ingest_in_progress"


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


def load_uploaded_documents(settings: Settings) -> Sequence[CatalogDocument]:
    """Return catalog rows for the uploaded-documents list."""
    return list_uploaded_documents(settings)


def _guard_in_progress(
    session: MutableMapping[str, object],
) -> UploadIngestResult | None:
    if session.get(_IN_PROGRESS_KEY):
        return UploadIngestResult(
            ok=False,
            message="A document operation is already in progress. Wait for it to finish.",
        )
    return None


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
    session: MutableMapping[str, object],
) -> UploadIngestResult:
    """Validate and create a new upload with a system-managed source ID."""
    blocked = _guard_in_progress(session)
    if blocked is not None:
        return blocked
    validated = _validate_upload(filename, content)
    if isinstance(validated, UploadIngestResult):
        return validated

    session[_IN_PROGRESS_KEY] = True
    try:
        try:
            document = create_uploaded_document(settings, validated)
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
    finally:
        session[_IN_PROGRESS_KEY] = False


def replace_existing_document(
    settings: Settings,
    *,
    reference: SourceReference,
    filename: str | None,
    content: bytes | None,
    session: MutableMapping[str, object],
) -> UploadIngestResult:
    """Replace content for a selected catalog document under the same ID."""
    blocked = _guard_in_progress(session)
    if blocked is not None:
        return blocked
    validated = _validate_upload(filename, content)
    if isinstance(validated, UploadIngestResult):
        return validated

    session[_IN_PROGRESS_KEY] = True
    try:
        try:
            document = replace_uploaded_document(settings, reference, validated)
        except DocumentUploadError as error:
            return UploadIngestResult(ok=False, message=str(error))
        except DocumentOperationError as error:
            return UploadIngestResult(
                ok=False,
                message=(
                    f"{error} Replacement did not complete; retry Replace or Delete."
                ),
            )
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
    finally:
        session[_IN_PROGRESS_KEY] = False


def delete_existing_document(
    settings: Settings,
    *,
    reference: SourceReference,
    session: MutableMapping[str, object],
) -> UploadIngestResult:
    """Delete vector chunks and the catalog row for a selected document."""
    blocked = _guard_in_progress(session)
    if blocked is not None:
        return blocked

    session[_IN_PROGRESS_KEY] = True
    try:
        try:
            delete_uploaded_document(settings, reference)
        except DocumentOperationError as error:
            return UploadIngestResult(
                ok=False,
                message=(
                    f"{error} Retry Delete to finish removing the catalog row."
                ),
            )
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
    finally:
        session[_IN_PROGRESS_KEY] = False
