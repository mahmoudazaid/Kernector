"""HTTP adapter tests for uploaded-document routes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from composition.errors import (
    DocumentOperationError,
    MissingUploadContentError,
    PartialDocumentOperationError,
    UnknownUploadedDocumentError,
)
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceReference,
    SourceType,
    UploadPayload,
)
from presentation.http import deps as http_deps
from presentation.http.app import create_app
from presentation.http.deps import DocumentOperations, get_document_operations
from presentation.failure_messages import OPERATIONAL_FAILURE_MESSAGE

_SUFFIXES = frozenset({".markdown", ".md", ".pdf", ".txt"})
_MAX_BYTES = 5_242_880


def _document(
    *,
    source_id: str = "src-1",
    file_name: str = "spec.md",
    content_format: str | None = "markdown",
    status: CatalogStatus = CatalogStatus.READY,
    error: str | None = None,
    chunk_count: int = 7,
    source_type: str = SourceType.KNOWLEDGE_DOCUMENT,
) -> CatalogDocument:
    return CatalogDocument(
        reference=SourceReference(
            source_id=source_id,
            source_type=source_type,
        ),
        file_name=file_name,
        title="Spec",
        content_format=content_format,
        status=status,
        uploaded_at=datetime(2026, 9, 5, 9, 12, 44, tzinfo=UTC),
        chunk_count=chunk_count,
        error=error,
    )


def _stub_ops(
    *,
    documents: tuple[CatalogDocument, ...] = (),
    list_error: Exception | None = None,
    create_impl: Any = None,
    replace_impl: Any = None,
    delete_impl: Any = None,
    get_content_impl: Any = None,
) -> tuple[DocumentOperations, dict[str, list[Any]]]:
    ledger: dict[str, list[Any]] = {
        "created": [],
        "replaced": [],
        "deleted": [],
        "content": [],
    }

    def list_docs() -> tuple[CatalogDocument, ...]:
        if list_error is not None:
            raise list_error
        return documents

    def create(payload: UploadPayload) -> CatalogDocument:
        ledger["created"].append(payload)
        if create_impl is not None:
            return create_impl(payload)
        return _document(source_id="new-id", file_name=payload.file_name)

    def replace(
        reference: SourceReference, payload: UploadPayload
    ) -> CatalogDocument:
        ledger["replaced"].append((reference, payload))
        if replace_impl is not None:
            return replace_impl(reference, payload)
        return _document(
            source_id=reference.source_id, file_name=payload.file_name
        )

    def delete(reference: SourceReference) -> None:
        ledger["deleted"].append(reference)
        if delete_impl is not None:
            delete_impl(reference)

    def get_content(source_id: str) -> tuple[CatalogDocument, UploadPayload]:
        ledger["content"].append(source_id)
        if get_content_impl is not None:
            return get_content_impl(source_id)
        document = next(
            (row for row in documents if row.reference.source_id == source_id),
            None,
        )
        if document is None:
            raise UnknownUploadedDocumentError("missing")
        return document, UploadPayload(
            file_name=document.file_name,
            content=b"# stored content",
        )

    ops = DocumentOperations(
        list=list_docs,
        create=create,
        replace=replace,
        delete=delete,
        get_content=get_content,
        supported_suffixes=_SUFFIXES,
        max_upload_bytes=_MAX_BYTES,
    )
    return ops, ledger


@pytest.fixture
def client_factory():
    def _make(ops: DocumentOperations) -> TestClient:
        app = create_app(cors_origins=("http://localhost:3000",))
        app.dependency_overrides[get_document_operations] = lambda: ops
        return TestClient(app)

    return _make


def test_list_documents_returns_envelope_without_constraints(client_factory) -> None:
    ops, _ledger = _stub_ops(
        documents=(
            _document(source_id="a", file_name="a.md"),
            _document(source_id="b", file_name="b.pdf", status=CatalogStatus.FAILED, error="vendor boom"),
        )
    )
    client = client_factory(ops)

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"documents"}
    assert "constraints" not in body
    assert len(body["documents"]) == 2
    assert body["documents"][0]["source_id"] == "a"
    assert body["documents"][1]["has_error"] is True
    assert "vendor boom" not in response.text


def test_list_documents_catalog_failure_is_sanitized_500(client_factory) -> None:
    ops, _ledger = _stub_ops(
        list_error=DocumentOperationError("catalog at /var/secret/uploads.json")
    )
    client = client_factory(ops)

    response = client.get("/api/v1/documents")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "operational_error"
    assert body["detail"] == OPERATIONAL_FAILURE_MESSAGE
    assert "/var/secret" not in response.text


def test_create_document_calls_create_not_replace(client_factory) -> None:
    ops, ledger = _stub_ops()
    client = client_factory(ops)

    response = client.post(
        "/api/v1/documents",
        files={"file": ("spec.md", b"# hello", "text/markdown")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source_id"] == "new-id"
    assert body["file_name"] == "spec.md"
    assert len(ledger["created"]) == 1
    assert len(ledger["replaced"]) == 0


def test_create_rejects_missing_file(client_factory) -> None:
    ops, _ledger = _stub_ops()
    client = client_factory(ops)

    response = client.post("/api/v1/documents")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "missing_upload_file"
    assert body["detail"] == "Choose a document to upload before submitting."


def test_create_rejects_unsupported_suffix(client_factory) -> None:
    ops, _ledger = _stub_ops()
    client = client_factory(ops)

    response = client.post(
        "/api/v1/documents",
        files={
            "file": (
                "notes.docx",
                b"pk",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "unsupported_document_type"
    assert ".docx" in body["detail"]
    assert ".md" in body["detail"]


def test_create_rejects_oversize_body(client_factory) -> None:
    ops = DocumentOperations(
        list=lambda: (),
        create=lambda _p: _document(),
        replace=lambda _r, _p: _document(),
        delete=lambda _r: None,
        get_content=lambda _source_id: (_document(), UploadPayload("tiny.md", b"x")),
        supported_suffixes=_SUFFIXES,
        max_upload_bytes=8,
    )
    client = client_factory(ops)

    response = client.post(
        "/api/v1/documents",
        files={"file": ("tiny.md", b"0123456789", "text/markdown")},
    )

    assert response.status_code == 413
    body = response.json()
    assert body["code"] == "upload_too_large"
    assert "8" in body["detail"]


def test_create_rejects_zero_byte_file(client_factory) -> None:
    ops, _ledger = _stub_ops()
    client = client_factory(ops)

    response = client.post(
        "/api/v1/documents",
        files={"file": ("empty.md", b"", "text/markdown")},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "missing_upload_file"
    assert body["detail"] == "Choose a document to upload before submitting."


def test_blank_source_id_is_422_not_500(client_factory) -> None:
    ops, ledger = _stub_ops()
    client = client_factory(ops)

    put = client.put(
        "/api/v1/documents/%20",
        files={"file": ("spec.md", b"# x", "text/markdown")},
    )
    delete = client.delete("/api/v1/documents/%20")

    assert put.status_code == 422
    assert put.json()["code"] == "validation_error"
    assert delete.status_code == 422
    assert delete.json()["code"] == "validation_error"
    assert ledger["replaced"] == []
    assert ledger["deleted"] == []


def test_replace_keeps_source_id_and_forces_knowledge_document(
    client_factory,
) -> None:
    ops, ledger = _stub_ops(documents=(_document(source_id="keep-me"),))
    client = client_factory(ops)

    response = client.put(
        "/api/v1/documents/keep-me",
        files={"file": ("other.md", b"# replaced", "text/markdown")},
    )

    assert response.status_code == 200
    assert response.json()["source_id"] == "keep-me"
    reference, payload = ledger["replaced"][0]
    assert reference.source_id == "keep-me"
    assert reference.source_type == SourceType.KNOWLEDGE_DOCUMENT
    assert payload.file_name == "other.md"


def test_replace_unknown_source_id_is_404(client_factory) -> None:
    def _replace(_ref: SourceReference, _payload: UploadPayload) -> CatalogDocument:
        raise UnknownUploadedDocumentError("missing")

    ops, _ledger = _stub_ops(replace_impl=_replace)
    client = client_factory(ops)

    response = client.put(
        "/api/v1/documents/missing",
        files={"file": ("spec.md", b"# x", "text/markdown")},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "document_not_found"


def test_delete_returns_204_empty_body(client_factory) -> None:
    ops, ledger = _stub_ops(documents=(_document(),))
    client = client_factory(ops)

    response = client.delete("/api/v1/documents/src-1")

    assert response.status_code == 204
    assert response.content == b""
    assert ledger["deleted"][0].source_id == "src-1"


def test_delete_unknown_document_is_204_noop_so_retry_converges(
    client_factory,
) -> None:
    """Missing rows are no-ops: partial-delete recovery retries must not 404."""

    def _delete(_ref: SourceReference) -> None:
        return None

    ops, ledger = _stub_ops(delete_impl=_delete)
    client = client_factory(ops)

    response = client.delete("/api/v1/documents/already-gone")

    assert response.status_code == 204
    assert ledger["deleted"][0].source_id == "already-gone"


@pytest.mark.parametrize(
    ("content_format", "file_name", "expected_type"),
    [
        ("txt", "notes.txt", "text/plain; charset=utf-8"),
        ("markdown", "notes.md", "text/plain; charset=utf-8"),
        ("pdf", "notes.pdf", "application/pdf"),
    ],
)
def test_content_serves_canonical_media_type_per_format(
    client_factory, content_format: str, file_name: str, expected_type: str
) -> None:
    document = _document(file_name=file_name, content_format=content_format)
    ops, _ledger = _stub_ops(documents=(document,))
    client = client_factory(ops)

    response = client.get("/api/v1/documents/src-1/content")

    assert response.status_code == 200
    assert response.headers["content-type"] == expected_type
    assert response.content == b"# stored content"


def test_content_unknown_source_id_is_404(client_factory) -> None:
    ops, _ledger = _stub_ops()
    client = client_factory(ops)

    response = client.get("/api/v1/documents/missing/content")

    assert response.status_code == 404
    assert response.json()["code"] == "document_not_found"


def test_content_google_drive_row_is_404(client_factory) -> None:
    drive = _document(
        source_id="drive-1",
        source_type=SourceType.GOOGLE_DRIVE,
    )

    def _get_content(_source_id: str):
        raise UnknownUploadedDocumentError("missing")

    ops, _ledger = _stub_ops(documents=(drive,), get_content_impl=_get_content)
    client = client_factory(ops)

    response = client.get("/api/v1/documents/drive-1/content")

    assert response.status_code == 404
    assert response.json()["code"] == "document_not_found"


def test_content_missing_blob_is_distinct_404(client_factory) -> None:
    def _get_content(_source_id: str):
        raise MissingUploadContentError("no stored content for this document")

    ops, _ledger = _stub_ops(get_content_impl=_get_content)
    client = client_factory(ops)

    response = client.get("/api/v1/documents/src-1/content")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "document_content_unavailable"
    assert body["detail"] == "no stored content for this document"


def test_content_unmapped_format_is_422_not_missing(client_factory) -> None:
    document = _document(content_format="rst", file_name="notes.rst")
    ops, _ledger = _stub_ops(documents=(document,))
    client = client_factory(ops)

    response = client.get("/api/v1/documents/src-1/content")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "document_preview_unsupported"
    assert "preview" in body["detail"].lower()


def test_failed_row_still_serves_content(client_factory) -> None:
    failed = _document(status=CatalogStatus.FAILED, error="embedding failed")
    ops, _ledger = _stub_ops(documents=(failed,))
    client = client_factory(ops)

    response = client.get("/api/v1/documents/src-1/content")

    assert response.status_code == 200
    assert response.content == b"# stored content"


def test_txt_upload_with_html_part_type_serves_text_plain(client_factory) -> None:
    stored: dict[str, tuple[CatalogDocument, UploadPayload]] = {}

    def _create(payload: UploadPayload) -> CatalogDocument:
        document = _document(
            source_id="new-id",
            file_name=payload.file_name,
            content_format="txt",
        )
        stored["new-id"] = (document, payload)
        return document

    def _get_content(source_id: str):
        return stored[source_id]

    ops, _ledger = _stub_ops(create_impl=_create, get_content_impl=_get_content)
    client = client_factory(ops)

    created = client.post(
        "/api/v1/documents",
        files={"file": ("notes.txt", b"<h1>not html</h1>", "text/html")},
    )
    response = client.get(f"/api/v1/documents/{created.json()['source_id']}/content")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.content == b"<h1>not html</h1>"


def test_content_security_headers_and_download_attachment(client_factory) -> None:
    ops, _ledger = _stub_ops(documents=(_document(file_name='bad"name.md'),))
    client = client_factory(ops)

    inline = client.get("/api/v1/documents/src-1/content")
    download = client.get("/api/v1/documents/src-1/download")

    assert inline.status_code == 200
    assert inline.headers["x-content-type-options"] == "nosniff"
    assert inline.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert inline.headers["cache-control"] == "private, no-store"
    assert inline.headers["content-disposition"].startswith("inline;")
    assert download.status_code == 200
    assert download.headers["content-security-policy"] == "default-src 'none'"
    assert download.headers["content-disposition"].startswith("attachment;")
    assert '"' in download.headers["content-disposition"]
    assert 'bad"name' not in download.headers["content-disposition"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/documents/%2E%2E/content",
        "/api/v1/documents/%2E/download",
    ],
)
def test_content_paths_reject_dot_segments(client_factory, path: str) -> None:
    ops, ledger = _stub_ops(documents=(_document(),))
    client = client_factory(ops)

    response = client.get(path)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert ledger["content"] == []


def test_delete_accepts_non_blank_ids_without_blob_charset_rule(
    client_factory,
) -> None:
    """Delete stays catalog-identity based; charset rules are content/download only."""
    ops, ledger = _stub_ops()
    client = client_factory(ops)

    response = client.delete("/api/v1/documents/%2E%2E")

    assert response.status_code == 204
    assert [ref.source_id for ref in ledger["deleted"]] == [".."]


def test_filesystem_delete_dotdot_is_noop_without_touching_blob_root(
    tmp_path: Path,
) -> None:
    from domain.knowledge import SourceReference, SourceType, UploadPayload
    from infrastructure.documents.upload_blob_store import (
        FilesystemUploadBlobStore,
    )

    blob_root = tmp_path / "blobs"
    blob_root.mkdir()
    marker = blob_root / "keep"
    marker.write_bytes(b"still here")
    store = FilesystemUploadBlobStore(blob_root)
    store.put(
        SourceReference("safe-id", SourceType.KNOWLEDGE_DOCUMENT),
        UploadPayload(file_name="ok.md", content=b"# ok"),
    )

    store.delete(SourceReference("..", SourceType.KNOWLEDGE_DOCUMENT))

    assert marker.read_bytes() == b"still here"
    assert (blob_root / "safe-id").is_file()


def test_download_unmapped_format_falls_back_to_octet_stream(client_factory) -> None:
    document = _document(content_format="rst", file_name="notes.rst")
    ops, _ledger = _stub_ops(documents=(document,))
    client = client_factory(ops)

    response = client.get("/api/v1/documents/src-1/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.content == b"# stored content"


def test_download_exposes_content_disposition_for_cors(client_factory) -> None:
    ops, _ledger = _stub_ops(documents=(_document(),))
    client = client_factory(ops)

    response = client.get(
        "/api/v1/documents/src-1/download",
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-expose-headers"] == "Content-Disposition"


@pytest.mark.parametrize(
    ("method", "path", "operation"),
    [
        ("post", "/api/v1/documents", "create"),
        ("put", "/api/v1/documents/src-1", "replace"),
        ("delete", "/api/v1/documents/src-1", "delete"),
    ],
)
def test_partial_failure_returns_409_with_retry_sentence(
    client_factory, method: str, path: str, operation: str
) -> None:
    def _create(_p: UploadPayload) -> CatalogDocument:
        raise PartialDocumentOperationError("half", operation="create")

    def _replace(_r: SourceReference, _p: UploadPayload) -> CatalogDocument:
        raise PartialDocumentOperationError("half", operation="replace")

    def _delete(_r: SourceReference) -> None:
        raise PartialDocumentOperationError("half", operation="delete")

    ops, _ledger = _stub_ops(
        documents=(_document(),),
        create_impl=_create, replace_impl=_replace, delete_impl=_delete
    )
    client = client_factory(ops)
    kwargs: dict[str, Any] = {}
    if method in {"post", "put"}:
        kwargs["files"] = {"file": ("spec.md", b"# x", "text/markdown")}

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "document_partial_failure"
    assert "retry" in body["detail"].lower()
    assert "half" not in body["detail"]


def test_document_operations_resolve_catalog_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def boom() -> object:
        calls.append(1)
        raise DocumentOperationError("catalog unavailable")

    monkeypatch.setattr(http_deps, "get_document_catalog", boom)
    ops = http_deps.get_document_operations(SimpleNamespace(max_upload_bytes=1))
    assert calls == []
    with pytest.raises(DocumentOperationError, match="catalog unavailable"):
        ops.list()
    assert calls == [1]


def test_document_operations_reuse_the_process_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = object()
    seen: list[tuple[str, object]] = []
    monkeypatch.setattr(http_deps, "get_document_catalog", lambda: catalog)
    monkeypatch.setattr(http_deps, "get_vector_store", lambda: object())

    def record(name: str):
        def _fn(*_args, catalog=None, **_kwargs):
            seen.append((name, catalog))
            if name == "list":
                return ()
            if name == "delete":
                return None
            return object()

        return _fn

    monkeypatch.setattr(http_deps, "list_uploaded_documents", record("list"))
    monkeypatch.setattr(http_deps, "create_uploaded_document", record("create"))
    monkeypatch.setattr(http_deps, "replace_uploaded_document", record("replace"))
    monkeypatch.setattr(http_deps, "delete_uploaded_document", record("delete"))
    monkeypatch.setattr(http_deps, "get_uploaded_document_content", record("content"))
    ops = http_deps.get_document_operations(SimpleNamespace(max_upload_bytes=1))
    ops.list()
    ops.create(object())
    ops.replace(object(), object())
    ops.delete(object())
    ops.get_content("src-1")
    assert seen == [
        ("list", catalog),
        ("create", catalog),
        ("replace", catalog),
        ("delete", catalog),
        ("content", catalog),
    ]
