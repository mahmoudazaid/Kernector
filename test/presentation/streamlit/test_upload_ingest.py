"""Behavior tests for Streamlit document-management helpers.

Composition is monkeypatched at symbols imported into
``presentation.streamlit.upload_ingest`` so tests stay offline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from application.errors import ApplicationValidationError, ConfigurationError
from composition import DocumentOperationError, DocumentUploadError
from domain.errors import DomainValidationError
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceReference,
    SourceType,
    UploadPayload,
)
from presentation.streamlit import upload_ingest as upload_mod


def _document(source_id: str = "id-1", file_name: str = "guide.md") -> CatalogDocument:
    return CatalogDocument(
        reference=SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT),
        file_name=file_name,
        title="guide",
        content_format="markdown",
        status=CatalogStatus.READY,
        uploaded_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        chunk_count=3,
        error=None,
    )


def test_missing_file_rejects_create_without_calling_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        upload_mod,
        "create_uploaded_document",
        lambda *a, **k: calls.append((a, k)),
    )
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.create_new_document(
        object(),
        filename=None,
        content=None,
        session=session,
    )

    assert result.ok is False
    assert result.message.strip()
    assert calls == []
    assert session["ingest_in_progress"] is False


def test_in_progress_rejects_create_without_calling_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        upload_mod,
        "create_uploaded_document",
        lambda *a, **k: calls.append((a, k)),
    )
    session: dict[str, object] = {"ingest_in_progress": True}

    result = upload_mod.create_new_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        session=session,
    )

    assert result.ok is False
    assert calls == []
    assert session["ingest_in_progress"] is True


def test_create_sets_flag_during_composition_and_clears_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[bool] = []
    document = _document()

    def _create(_settings: object, payload: UploadPayload) -> CatalogDocument:
        observed.append(bool(session["ingest_in_progress"]))
        assert payload.file_name == "guide.txt"
        return document

    monkeypatch.setattr(upload_mod, "create_uploaded_document", _create)
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.create_new_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        session=session,
    )

    assert result.ok is True
    assert result.should_rerun is True
    assert result.document == document
    assert "id-1" in result.message
    assert observed == [True]
    assert session["ingest_in_progress"] is False


def test_unsupported_suffix_rejected_before_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        upload_mod,
        "create_uploaded_document",
        lambda *a, **k: calls.append((a, k)),
    )
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.create_new_document(
        object(),
        filename="notes.docx",
        content=b"hello",
        session=session,
    )

    assert result.ok is False
    assert "unsupported" in result.message.lower()
    assert calls == []


@pytest.mark.parametrize(
    ("error", "needle"),
    [
        (DocumentUploadError("bad upload"), "bad upload"),
        (DocumentOperationError("partial"), "partial"),
        (DomainValidationError("blank"), "blank"),
        (ApplicationValidationError("bad request"), "bad request"),
        (ConfigurationError("missing key"), "missing key"),
    ],
)
def test_typed_create_failures_map_to_specific_messages(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    needle: str,
) -> None:
    def _create(*_a: object, **_k: object) -> CatalogDocument:
        raise error

    monkeypatch.setattr(upload_mod, "create_uploaded_document", _create)
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.create_new_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        session=session,
    )

    assert result.ok is False
    assert needle in result.message
    assert session["ingest_in_progress"] is False


def test_replace_preserves_reference_in_success_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document(file_name="guide-v2.md")

    def _replace(
        _settings: object, reference: SourceReference, payload: UploadPayload
    ) -> CatalogDocument:
        assert reference.source_id == "id-1"
        assert payload.file_name == "guide-v2.md"
        return document

    monkeypatch.setattr(upload_mod, "replace_uploaded_document", _replace)
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.replace_existing_document(
        object(),
        reference=document.reference,
        filename="guide-v2.md",
        content=b"hello",
        session=session,
    )

    assert result.ok is True
    assert "unchanged" in result.message.lower()
    assert "id-1" in result.message


def test_delete_partial_failure_mentions_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _delete(*_a: object, **_k: object) -> None:
        raise DocumentOperationError("chunks removed but catalog row remains")

    monkeypatch.setattr(upload_mod, "delete_uploaded_document", _delete)
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.delete_existing_document(
        object(),
        reference=_document().reference,
        session=session,
    )

    assert result.ok is False
    assert "retry" in result.message.lower()


def test_unexpected_exception_is_logged_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _create(*_a: object, **_k: object) -> CatalogDocument:
        raise RuntimeError("secret internals")

    monkeypatch.setattr(upload_mod, "create_uploaded_document", _create)
    session: dict[str, object] = {"ingest_in_progress": False}

    with caplog.at_level("ERROR"):
        result = upload_mod.create_new_document(
            object(),
            filename="guide.txt",
            content=b"hello",
            session=session,
        )

    assert result.ok is False
    assert "secret internals" not in result.message
    assert "unexpectedly" in result.message.lower()
    assert any("Unexpected failure" in record.message for record in caplog.records)


def test_streamlit_app_imports_without_infrastructure_documents() -> None:
    """Presentation stays above the document adapter boundary."""
    import presentation.streamlit.app as app_mod
    import presentation.streamlit.upload_ingest as helper_mod

    for module in (app_mod, helper_mod):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "infrastructure.documents" not in source
        assert "infrastructure.catalog" not in source
        assert "pypdf" not in source
        assert "extract_document" not in source
        assert "JsonDocumentCatalog" not in source
