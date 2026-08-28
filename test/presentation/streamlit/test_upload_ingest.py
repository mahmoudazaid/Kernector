"""Behavior tests for Streamlit document-management helpers.

Composition is monkeypatched at symbols imported into
``presentation.streamlit.upload_ingest`` so tests stay offline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from application.errors import ApplicationValidationError, ConfigurationError
from composition import (
    DocumentOperationError,
    DocumentUploadError,
    PartialDocumentOperationError,
)
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

    result = upload_mod.create_new_document(object(), filename=None, content=None)

    assert result.ok is False
    assert result.message.strip()
    assert calls == []


def test_create_returns_source_id_for_the_success_banner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document()

    def _create(_settings: object, payload: UploadPayload) -> CatalogDocument:
        assert payload.file_name == "guide.txt"
        return document

    monkeypatch.setattr(upload_mod, "create_uploaded_document", _create)

    result = upload_mod.create_new_document(
        object(), filename="guide.txt", content=b"hello"
    )

    assert result.ok is True
    assert result.should_rerun is True
    assert result.document == document
    assert "id-1" in result.message


def test_unsupported_suffix_rejected_before_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        upload_mod,
        "create_uploaded_document",
        lambda *a, **k: calls.append((a, k)),
    )

    result = upload_mod.create_new_document(
        object(), filename="notes.docx", content=b"hello"
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

    result = upload_mod.create_new_document(
        object(), filename="guide.txt", content=b"hello"
    )

    assert result.ok is False
    assert needle in result.message


def test_create_partial_failure_is_actionable_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The upload half-landed: say what to do, not what the server saw."""

    def _create(*_a: object, **_k: object) -> CatalogDocument:
        raise PartialDocumentOperationError(
            "could not write catalog at /srv/kernector/data/uploads.json"
        ) from RuntimeError("openrouter rejected key sk-live-abc123")

    monkeypatch.setattr(upload_mod, "create_uploaded_document", _create)

    with caplog.at_level("ERROR"):
        result = upload_mod.create_new_document(
            object(), filename="guide.txt", content=b"hello"
        )

    assert result.ok is False
    assert result.document is None
    assert result.message == (
        "Upload failed and its status could not be saved; retry, or delete any "
        "visible pending document."
    )
    assert "/srv/kernector/data/uploads.json" not in result.message
    assert "sk-live-abc123" not in result.message
    assert any(record.exc_info for record in caplog.records)


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

    result = upload_mod.replace_existing_document(
        object(),
        reference=document.reference,
        filename="guide-v2.md",
        content=b"hello",
    )

    assert result.ok is True
    assert "unchanged" in result.message.lower()
    assert "id-1" in result.message


def test_partial_delete_failure_names_the_action_to_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _delete(*_a: object, **_k: object) -> None:
        raise PartialDocumentOperationError(
            "chunks removed but catalog row remains"
        )

    monkeypatch.setattr(upload_mod, "delete_uploaded_document", _delete)

    result = upload_mod.delete_existing_document(
        object(), reference=_document().reference
    )

    assert result.ok is False
    assert "retry" in result.message.lower()


def test_delete_failure_that_changed_nothing_promises_no_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing was mutated, so the message must not send the user chasing state."""

    def _delete(*_a: object, **_k: object) -> None:
        raise DocumentOperationError("could not open the vector store")

    monkeypatch.setattr(upload_mod, "delete_uploaded_document", _delete)

    result = upload_mod.delete_existing_document(
        object(), reference=_document().reference
    )

    assert result.ok is False
    assert result.message == "could not open the vector store"
    assert "retry" not in result.message.lower()


def test_partial_replace_failure_names_the_actions_to_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _replace(*_a: object, **_k: object) -> CatalogDocument:
        raise PartialDocumentOperationError("degraded row written")

    monkeypatch.setattr(upload_mod, "replace_uploaded_document", _replace)

    result = upload_mod.replace_existing_document(
        object(),
        reference=_document().reference,
        filename="guide.md",
        content=b"hello",
    )

    assert result.ok is False
    assert "retry replace or delete" in result.message.lower()


def test_replace_failure_that_changed_nothing_promises_no_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _replace(*_a: object, **_k: object) -> CatalogDocument:
        raise DocumentOperationError("unknown document knowledge_document:id-1")

    monkeypatch.setattr(upload_mod, "replace_uploaded_document", _replace)

    result = upload_mod.replace_existing_document(
        object(),
        reference=_document().reference,
        filename="guide.md",
        content=b"hello",
    )

    assert result.ok is False
    assert result.message == "unknown document knowledge_document:id-1"


def test_unexpected_exception_is_logged_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _create(*_a: object, **_k: object) -> CatalogDocument:
        raise RuntimeError("secret internals")

    monkeypatch.setattr(upload_mod, "create_uploaded_document", _create)

    with caplog.at_level("ERROR"):
        result = upload_mod.create_new_document(
            object(), filename="guide.txt", content=b"hello"
        )

    assert result.ok is False
    assert "secret internals" not in result.message
    assert "unexpectedly" in result.message.lower()
    assert any("Unexpected failure" in record.message for record in caplog.records)


def test_listing_returns_rows_when_composition_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document()
    monkeypatch.setattr(
        upload_mod, "list_uploaded_documents", lambda _settings: (document,)
    )

    listing = upload_mod.load_uploaded_documents(object())

    assert listing.documents == (document,)
    assert listing.error is None


def test_listing_reports_typed_failures_as_page_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _list(*_a: object, **_k: object) -> tuple[CatalogDocument, ...]:
        raise ConfigurationError("Missing OPENROUTER_API_KEY.")

    monkeypatch.setattr(upload_mod, "list_uploaded_documents", _list)

    listing = upload_mod.load_uploaded_documents(object())

    assert listing.documents == ()
    assert listing.error is not None
    assert "Missing OPENROUTER_API_KEY." in listing.error


def test_listing_logs_unexpected_failures_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _list(*_a: object, **_k: object) -> tuple[CatalogDocument, ...]:
        raise RuntimeError("secret internals")

    monkeypatch.setattr(upload_mod, "list_uploaded_documents", _list)

    with caplog.at_level("ERROR"):
        listing = upload_mod.load_uploaded_documents(object())

    assert listing.documents == ()
    assert listing.error is not None
    assert "secret internals" not in listing.error
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
