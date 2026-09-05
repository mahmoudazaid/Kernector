"""Uploaded-document HTTP routes (list / create / replace / delete)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response

from domain.knowledge import SourceReference, SourceType, UploadPayload
from presentation.http.deps import DocumentOperationsDep
from presentation.http.errors import (
    UnsupportedDocumentTypeError,
    UploadTooLargeError,
    problem_responses,
)
from presentation.http.schemas import (
    CatalogDocumentResponse,
    DocumentListResponse,
    DocumentUploadConstraintsResponse,
    catalog_document_response,
)

router = APIRouter(prefix="/api/v1", tags=["documents"])

_MISSING_FILE_MSG = "Choose a document to upload before submitting."


def _missing_file_error() -> RequestValidationError:
    return RequestValidationError(
        [
            {
                "type": "missing",
                "loc": ("body", "file"),
                "msg": _MISSING_FILE_MSG,
                "input": None,
            }
        ]
    )


def _read_upload(
    upload: UploadFile | None,
    *,
    max_upload_bytes: int,
    supported_suffixes: frozenset[str],
) -> UploadPayload:
    """Validate multipart file and return an application payload."""
    if upload is None or not upload.filename:
        raise _missing_file_error()

    advisory = upload.size
    if advisory is not None and advisory > max_upload_bytes:
        raise UploadTooLargeError(max_bytes=max_upload_bytes)

    content = upload.file.read()
    if len(content) > max_upload_bytes:
        raise UploadTooLargeError(max_bytes=max_upload_bytes)
    if len(content) == 0:
        raise _missing_file_error()

    suffix = Path(upload.filename).suffix.lower()
    if suffix not in supported_suffixes:
        raise UnsupportedDocumentTypeError(
            f"unsupported document type ({suffix!r}); supported types are "
            f"{', '.join(sorted(supported_suffixes))}"
        )
    return UploadPayload(file_name=upload.filename, content=content)


@router.get(
    "/documents",
    responses=problem_responses(405, 500),
)
def list_documents(ops: DocumentOperationsDep) -> DocumentListResponse:
    """Return uploaded catalog rows plus client upload constraints."""
    documents = ops.list()
    return DocumentListResponse(
        documents=[catalog_document_response(doc) for doc in documents],
        constraints=DocumentUploadConstraintsResponse(
            supported_suffixes=sorted(ops.supported_suffixes),
            max_upload_bytes=ops.max_upload_bytes,
        ),
    )


@router.post(
    "/documents",
    status_code=201,
    responses=problem_responses(405, 409, 413, 422, 500, 502),
)
def create_document(
    ops: DocumentOperationsDep,
    file: UploadFile | None = File(default=None),
) -> CatalogDocumentResponse:
    """Upload a new document; always allocates a system-managed source ID."""
    payload = _read_upload(
        file,
        max_upload_bytes=ops.max_upload_bytes,
        supported_suffixes=ops.supported_suffixes,
    )
    document = ops.create(payload)
    return catalog_document_response(document)


@router.put(
    "/documents/{source_id}",
    responses=problem_responses(404, 405, 409, 413, 422, 500, 502),
)
def replace_document(
    source_id: str,
    ops: DocumentOperationsDep,
    file: UploadFile | None = File(default=None),
) -> CatalogDocumentResponse:
    """Replace document content under the same source ID."""
    payload = _read_upload(
        file,
        max_upload_bytes=ops.max_upload_bytes,
        supported_suffixes=ops.supported_suffixes,
    )
    reference = SourceReference(
        source_id=source_id,
        source_type=SourceType.KNOWLEDGE_DOCUMENT,
    )
    document = ops.replace(reference, payload)
    return catalog_document_response(document)


@router.delete(
    "/documents/{source_id}",
    status_code=204,
    responses=problem_responses(405, 409, 500),
)
def delete_document(source_id: str, ops: DocumentOperationsDep) -> Response:
    """Delete chunks and catalog row. Unknown IDs are a deliberate 204 no-op."""
    reference = SourceReference(
        source_id=source_id,
        source_type=SourceType.KNOWLEDGE_DOCUMENT,
    )
    ops.delete(reference)
    return Response(status_code=204)
