"""Uploaded-document HTTP routes (list / create / replace / delete)."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response

from composition import UnsupportedPreviewFormatError
from composition import UPLOAD_CONTENT_TYPE_BY_FORMAT
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
    catalog_document_response,
)

router = APIRouter(prefix="/api/v1", tags=["documents"])

_SOURCE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
_PREVIEW_CONTENT_SECURITY_POLICY = "default-src 'none'; sandbox"
_DOWNLOAD_CONTENT_SECURITY_POLICY = "default-src 'none'"
_DOWNLOAD_FALLBACK_TYPE = "application/octet-stream"


def _content_success_response(
    description: str, *, include_octet_stream: bool = False
) -> dict:
    media_types = set(UPLOAD_CONTENT_TYPE_BY_FORMAT.values())
    if include_octet_stream:
        media_types.add(_DOWNLOAD_FALLBACK_TYPE)
    return {
        "description": description,
        "content": {
            media_type: {"schema": {"type": "string", "format": "binary"}}
            for media_type in media_types
        },
    }


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


def _require_blob_source_id(source_id: str) -> str:
    """Reject IDs that cannot be used as a blob-store path segment."""
    if _SOURCE_ID_PATTERN.fullmatch(source_id) is None:
        raise RequestValidationError(
            [
                {
                    "type": "string_pattern_mismatch",
                    "loc": ("path", "source_id"),
                    "msg": "source_id must be 1-64 URL-safe identifier characters",
                    "input": source_id,
                }
            ]
        )
    return source_id


def _download_filename(file_name: str) -> str:
    basename = Path(file_name).name.strip()
    if not basename:
        basename = "document"
    return basename.replace('"', "_").replace("\r", "_").replace("\n", "_")


def _content_disposition(disposition: str, file_name: str) -> str:
    filename = _download_filename(file_name)
    ascii_name = "".join(char if ord(char) < 128 else "_" for char in filename)
    escaped = ascii_name.replace("\\", "_")
    value = f'{disposition}; filename="{escaped}"'
    if ascii_name != filename:
        value += f"; filename*=UTF-8''{quote(filename, safe='')}"
    return value


def _document_content_response(
    ops: DocumentOperationsDep,
    source_id: str,
    *,
    disposition: str,
    for_preview: bool,
) -> Response:
    source_id = _require_blob_source_id(source_id)
    row, payload = ops.get_content(source_id)
    media_type = UPLOAD_CONTENT_TYPE_BY_FORMAT.get(row.content_format or "")
    if media_type is None:
        if for_preview:
            raise UnsupportedPreviewFormatError(
                "Preview is not available for this document format."
            )
        media_type = _DOWNLOAD_FALLBACK_TYPE
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        "Content-Disposition": _content_disposition(
            disposition, row.file_name
        ),
        "Content-Security-Policy": (
            _PREVIEW_CONTENT_SECURITY_POLICY
            if for_preview
            else _DOWNLOAD_CONTENT_SECURITY_POLICY
        ),
    }
    return Response(
        content=bytes(payload.content),
        media_type=media_type,
        headers=headers,
    )


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


@router.get(
    "/documents/{source_id}/content",
    response_class=Response,
    responses={
        200: _content_success_response("Original document content"),
        **problem_responses(404, 405, 422, 500),
    },
)
def get_document_content(source_id: str, ops: DocumentOperationsDep) -> Response:
    """Return original uploaded bytes for inline display."""
    return _document_content_response(
        ops, source_id, disposition="inline", for_preview=True
    )


@router.get(
    "/documents/{source_id}/download",
    response_class=Response,
    responses={
        200: _content_success_response(
            "Original document download", include_octet_stream=True
        ),
        **problem_responses(404, 405, 422, 500),
    },
)
def download_document(source_id: str, ops: DocumentOperationsDep) -> Response:
    """Return original uploaded bytes as an attachment."""
    return _document_content_response(
        ops, source_id, disposition="attachment", for_preview=False
    )


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
