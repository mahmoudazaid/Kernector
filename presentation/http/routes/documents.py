"""Uploaded-document HTTP routes (list / create / replace / delete / chunks)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Query, UploadFile
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
    DocumentChunkListResponse,
    DocumentListResponse,
    catalog_document_response,
    document_chunk_response,
)

router = APIRouter(prefix="/api/v1", tags=["documents"])

_DEFAULT_CHUNK_LIMIT = 50
_MAX_CHUNK_LIMIT = 200


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
        raise UploadTooLargeError.for_file(
            limit_bytes=max_upload_bytes,
            actual_bytes=advisory,
        )

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.file.read(65_536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_upload_bytes:
            raise UploadTooLargeError.for_file(
                limit_bytes=max_upload_bytes,
                actual_bytes=total,
            )
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


@router.get(
    "/documents",
    responses=problem_responses(405, 500),
)
def list_documents(ops: DocumentOperationsDep) -> DocumentListResponse:
    """Return upload and Google Drive catalog rows for the documents UI."""
    documents = ops.list()
    return DocumentListResponse(
        documents=[catalog_document_response(doc) for doc in documents],
    )


@router.post(
    "/documents",
    status_code=201,
    responses=problem_responses(405, 409, 413, 422, 500),
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
    responses=problem_responses(404, 405, 409, 413, 422, 500),
)
def replace_document(
    source_id: str,
    ops: DocumentOperationsDep,
    file: UploadFile | None = File(default=None),
) -> CatalogDocumentResponse:
    """Replace document content under the same source ID."""
    source_id = _require_source_id(source_id)
    payload = _read_upload(
        file,
        max_upload_bytes=ops.max_upload_bytes,
        supported_suffixes=ops.supported_suffixes,
    )
    document = ops.replace(
        SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT),
        payload,
    )
    return catalog_document_response(document)


@router.delete(
    "/documents/{source_id}",
    status_code=204,
    responses=problem_responses(405, 409, 422, 500),
)
def delete_document(source_id: str, ops: DocumentOperationsDep) -> Response:
    """Delete chunks and catalog row. Unknown IDs are a deliberate 204 no-op."""
    source_id = _require_source_id(source_id)
    ops.delete(SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT))
    return Response(status_code=204)


@router.get(
    "/documents/{source_id}/chunks",
    responses=problem_responses(404, 405, 422, 500),
)
def list_document_chunks(
    source_id: str,
    ops: DocumentOperationsDep,
    source_type: SourceType = Query(...),
    limit: int = Query(
        default=_DEFAULT_CHUNK_LIMIT,
        ge=1,
        le=_MAX_CHUNK_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
) -> DocumentChunkListResponse:
    """Return a page of stored chunks for one catalogued source."""
    source_id = _require_source_id(source_id)
    page = ops.list_chunks(
        SourceReference(source_id, source_type),
        limit=limit,
        offset=offset,
    )
    return DocumentChunkListResponse(
        chunks=[document_chunk_response(chunk) for chunk in page.chunks],
        has_more=page.has_more,
    )
