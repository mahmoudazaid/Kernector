"""Upload-to-ingest helpers for the Streamlit presentation layer.

Owns validation, the in-flight guard, temporary-file lifecycle, and mapping of
composition results to UI-neutral messages. Widgets stay in ``app.py``.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path

from application.errors import ApplicationValidationError, ConfigurationError
from composition import (
    SUPPORTED_UPLOAD_SUFFIXES,
    DocumentUploadError,
    Settings,
    ingest_uploaded_document,
)
from domain.errors import DomainValidationError

logger = logging.getLogger(__name__)

_IN_PROGRESS_KEY = "ingest_in_progress"


@dataclass(frozen=True, slots=True)
class UploadIngestResult:
    """UI-neutral outcome of one upload submission.

    Attributes:
        ok (bool): Whether ingestion succeeded.
        message (str): User-facing success or error text.
    """

    ok: bool
    message: str


def _write_upload_tempfile(filename: str, content: bytes) -> Path:
    """Persist upload bytes under a managed temp path with a validated suffix."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise DocumentUploadError(
            f"unsupported document type ({suffix!r}); supported types are "
            f"{', '.join(sorted(SUPPORTED_UPLOAD_SUFFIXES))}"
        )
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(content)
        handle.flush()
    finally:
        handle.close()
    return Path(handle.name)


def submit_uploaded_document(
    settings: Settings,
    *,
    filename: str | None,
    content: bytes | None,
    source_id: str,
    session: MutableMapping[str, object],
) -> UploadIngestResult:
    """Validate, guard, ingest one upload, and always clear the in-flight flag.

    Args:
        settings (Settings): Runtime settings for composition ingest.
        filename (str | None): Client filename used only for suffix selection.
        content (bytes | None): Raw uploaded bytes.
        source_id (str): Caller-supplied source identity.
        session (MutableMapping[str, object]): Mutable mapping with
            ``ingest_in_progress`` (typically ``st.session_state``).

    Returns:
        UploadIngestResult: Success or failure message for the UI.
    """
    if session.get(_IN_PROGRESS_KEY):
        return UploadIngestResult(
            ok=False,
            message="Ingestion is already in progress. Wait for it to finish.",
        )
    if not filename or content is None:
        return UploadIngestResult(
            ok=False,
            message="Choose a document to upload before submitting.",
        )
    if not isinstance(source_id, str) or not source_id.strip():
        return UploadIngestResult(
            ok=False,
            message="Enter a non-blank source ID before submitting.",
        )

    session[_IN_PROGRESS_KEY] = True
    temp_path: Path | None = None
    try:
        try:
            temp_path = _write_upload_tempfile(filename, content)
            response = ingest_uploaded_document(
                settings, temp_path, source_id=source_id.strip()
            )
        except DocumentUploadError as error:
            return UploadIngestResult(ok=False, message=str(error))
        except DomainValidationError as error:
            return UploadIngestResult(ok=False, message=str(error))
        except ApplicationValidationError as error:
            return UploadIngestResult(ok=False, message=str(error))
        except ConfigurationError as error:
            return UploadIngestResult(ok=False, message=str(error))
        except Exception:
            logger.exception("Unexpected failure during document upload ingest")
            return UploadIngestResult(
                ok=False,
                message="Upload failed unexpectedly. Check the server logs.",
            )
        return UploadIngestResult(
            ok=True,
            message=(
                f"Accepted {len(response.accepted_ids)} document(s), "
                f"{response.chunk_count} chunk(s)."
            ),
        )
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        session[_IN_PROGRESS_KEY] = False
