"""HTTP adapter tests for uploaded-document routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from composition.errors import (
    DocumentOperationError,
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
from presentation.http.app import create_app
from presentation.http.deps import DocumentOperations, get_document_operations
from presentation.failure_messages import OPERATIONAL_FAILURE_MESSAGE

_SUFFIXES = frozenset({".markdown", ".md", ".pdf", ".txt"})
_MAX_BYTES = 5_242_880


def _document(
    *,
    source_id: str = "src-1",
    file_name: str = "spec.md",
    status: CatalogStatus = CatalogStatus.READY,
    error: str | None = None,
    chunk_count: int = 7,
) -> CatalogDocument:
    return CatalogDocument(
        reference=SourceReference(
            source_id=source_id,
            source_type=SourceType.KNOWLEDGE_DOCUMENT,
        ),
        file_name=file_name,
        title="Spec",
        content_format="markdown",
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
) -> tuple[DocumentOperations, dict[str, list[Any]]]:
    ledger: dict[str, list[Any]] = {
        "created": [],
        "replaced": [],
        "deleted": [],
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

    ops = DocumentOperations(
        list=list_docs,
        create=create,
        replace=replace,
        delete=delete,
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


def test_list_documents_returns_envelope_and_constraints(client_factory) -> None:
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
    assert set(body) == {"documents", "constraints"}
    assert body["constraints"] == {
        "supported_suffixes": [".markdown", ".md", ".pdf", ".txt"],
        "max_upload_bytes": _MAX_BYTES,
    }
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
    assert body["code"] == "validation_error"
    pointers = [err["pointer"] for err in body.get("errors", [])]
    assert "#/file" in pointers


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
    assert body["code"] == "validation_error"
    assert any(err["pointer"] == "#/file" for err in body.get("errors", []))


def test_replace_keeps_source_id_and_forces_knowledge_document(
    client_factory,
) -> None:
    ops, ledger = _stub_ops()
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
    ops, ledger = _stub_ops()
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

    ops, _ledger = _stub_ops(delete_impl=_delete)
    client = client_factory(ops)

    response = client.delete("/api/v1/documents/already-gone")

    assert response.status_code == 204


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
