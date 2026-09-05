"""Uploaded-document HTTP routes (list / create / replace / delete)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response

from composition import unsupported_upload_type_detail
from domain.knowledge import SourceReference, SourceType, UploadPayload
from presentation.http.deps import DocumentOperationsDep
from presentation.http.errors import (
    MissingUploadFileError,
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

# Multipart framing adds path/headers beyond the file bytes themselves.
_MULTIPART_OVERHEAD_BYTES = 64_000


def _require_source_id(source_id: str) -> str:
    """Reject blank/whitespace path segments before domain construction."""
    if not source_id.strip():
        raise RequestValidationError(
            [
                {
                    "type": "string_too_short",
                    "loc": ("path", "source_id"),
                    "msg": "source_id must not be blank",
                    "input": source_id,
                }
            ]
        )
    return source_id


def _read_upload(
    upload: UploadFile | None,
    *,
    max_upload_bytes: int,
    supported_suffixes: frozenset[str],
) -> UploadPayload:
    """Validate multipart file and return an application payload."""
    if upload is None or not upload.filename:
        raise MissingUploadFileError()

    advisory = upload.size
    if advisory is not None and advisory > max_upload_bytes:
        raise UploadTooLargeError(max_bytes=max_upload_bytes)

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.file.read(65_536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_upload_bytes:
            raise UploadTooLargeError(max_bytes=max_upload_bytes)
        chunks.append(chunk)
    content = b"".join(chunks)
    if len(content) == 0:
        raise MissingUploadFileError()

    suffix = Path(upload.filename).suffix.lower()
    if suffix not in supported_suffixes:
        raise UnsupportedDocumentTypeError(
            unsupported_upload_type_detail(suffix)
        )
    return UploadPayload(file_name=upload.filename, content=content)


async def _reject_oversized_content_length(
    request: Request, max_upload_bytes: int
) -> None:
    """Fail fast when Content-Length already exceeds the upload budget."""
    raw = request.headers.get("content-length")
    if raw is None:
        return
    try:
        length = int(raw)
    except ValueError:
        return
    if length > max_upload_bytes + _MULTIPART_OVERHEAD_BYTES:
        raise UploadTooLargeError(max_bytes=max_upload_bytes)


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
    responses=problem_responses(405, 409, 413, 422, 500),
)
async def create_document(
    request: Request,
    ops: DocumentOperationsDep,
    file: UploadFile | None = File(default=None),
) -> CatalogDocumentResponse:
    """Upload a new document; always allocates a system-managed source ID."""
    await _reject_oversized_content_length(request, ops.max_upload_bytes)
    payload = _read_upload(
        file,
        max_upload_bytes=ops.max_upload_bytes,
        supported_suffixes=ops.supported_suffixes,
    )
    document = ops.create(payload)
    return catalog_document_response(document)


@router.put(
    "/documents/{source_id}",
    responses=problem_responses(404, 405, 409, 413, 422, 500),
)
async def replace_document(
    source_id: str,
    request: Request,
    ops: DocumentOperationsDep,
    file: UploadFile | None = File(default=None),
) -> CatalogDocumentResponse:
    """Replace document content under the same source ID."""
    source_id = _require_source_id(source_id)
    await _reject_oversized_content_length(request, ops.max_upload_bytes)
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
    responses=problem_responses(405, 409, 422, 500),
)
def delete_document(source_id: str, ops: DocumentOperationsDep) -> Response:
    """Delete chunks and catalog row. Unknown IDs are a deliberate 204 no-op."""
    source_id = _require_source_id(source_id)
    reference = SourceReference(
        source_id=source_id,
        source_type=SourceType.KNOWLEDGE_DOCUMENT,
    )
    ops.delete(reference)
    return Response(status_code=204)
