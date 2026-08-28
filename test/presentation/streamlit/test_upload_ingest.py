"""Behavior tests for Streamlit upload-ingest helpers.

Composition is monkeypatched at symbols imported into
``presentation.streamlit.upload_ingest`` so tests stay offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from application.contracts import IngestResponse
from application.errors import ApplicationValidationError, ConfigurationError
from composition import DocumentUploadError
from domain.errors import DomainValidationError
from presentation.streamlit import upload_ingest as upload_mod


def test_missing_file_rejects_without_calling_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        upload_mod,
        "ingest_uploaded_document",
        lambda *a, **k: calls.append((a, k)),
    )
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.submit_uploaded_document(
        object(),
        filename=None,
        content=None,
        source_id="doc-1",
        session=session,
    )

    assert result.ok is False
    assert result.message.strip()
    assert calls == []
    assert session["ingest_in_progress"] is False


@pytest.mark.parametrize("source_id", ["", "   ", "\n"])
def test_blank_source_id_rejects_without_calling_composition(
    monkeypatch: pytest.MonkeyPatch,
    source_id: str,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        upload_mod,
        "ingest_uploaded_document",
        lambda *a, **k: calls.append((a, k)),
    )
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.submit_uploaded_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        source_id=source_id,
        session=session,
    )

    assert result.ok is False
    assert result.message.strip()
    assert calls == []
    assert session["ingest_in_progress"] is False


def test_in_progress_rejects_without_calling_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        upload_mod,
        "ingest_uploaded_document",
        lambda *a, **k: calls.append((a, k)),
    )
    session: dict[str, object] = {"ingest_in_progress": True}

    result = upload_mod.submit_uploaded_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        source_id="doc-1",
        session=session,
    )

    assert result.ok is False
    assert result.message.strip()
    assert calls == []
    assert session["ingest_in_progress"] is True


def test_valid_submission_sets_flag_during_composition_and_clears_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[bool] = []

    def _ingest(_settings: object, path: Path, *, source_id: str) -> IngestResponse:
        observed.append(bool(session["ingest_in_progress"]))
        assert path.exists()
        assert source_id == "doc-1"
        return IngestResponse(accepted_ids=["doc-1"], chunk_count=1)

    monkeypatch.setattr(upload_mod, "ingest_uploaded_document", _ingest)
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.submit_uploaded_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        source_id="doc-1",
        session=session,
    )

    assert result.ok is True
    assert observed == [True]
    assert session["ingest_in_progress"] is False


def test_flag_cleared_after_document_upload_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _ingest(_settings: object, path: Path, *, source_id: str) -> IngestResponse:
        raise DocumentUploadError("unreadable")

    monkeypatch.setattr(upload_mod, "ingest_uploaded_document", _ingest)
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.submit_uploaded_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        source_id="doc-1",
        session=session,
    )

    assert result.ok is False
    assert session["ingest_in_progress"] is False


def test_flag_cleared_after_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _ingest(_settings: object, path: Path, *, source_id: str) -> IngestResponse:
        raise RuntimeError("boom")

    monkeypatch.setattr(upload_mod, "ingest_uploaded_document", _ingest)
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.submit_uploaded_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        source_id="doc-1",
        session=session,
    )

    assert result.ok is False
    assert session["ingest_in_progress"] is False


def test_invalid_submissions_create_no_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    created: list[Path] = []

    def _track_temp(*args: object, **kwargs: object) -> Path:
        path = tmp_path / "should-not-exist.txt"
        created.append(path)
        return path

    monkeypatch.setattr(upload_mod, "_write_upload_tempfile", _track_temp)
    session: dict[str, object] = {"ingest_in_progress": False}

    upload_mod.submit_uploaded_document(
        object(),
        filename=None,
        content=None,
        source_id="doc-1",
        session=session,
    )
    upload_mod.submit_uploaded_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        source_id="  ",
        session=session,
    )
    session["ingest_in_progress"] = True
    upload_mod.submit_uploaded_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        source_id="doc-1",
        session=session,
    )

    assert created == []


def test_uppercase_suffix_is_normalized_for_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Path] = []

    def _ingest(_settings: object, path: Path, *, source_id: str) -> IngestResponse:
        seen.append(path)
        assert path.suffix == ".md"
        return IngestResponse(accepted_ids=["doc-1"], chunk_count=1)

    monkeypatch.setattr(upload_mod, "ingest_uploaded_document", _ingest)
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.submit_uploaded_document(
        object(),
        filename="guide.MD",
        content=b"# hello",
        source_id="doc-1",
        session=session,
    )

    assert result.ok is True
    assert len(seen) == 1
    assert not seen[0].exists()


def test_temp_file_removed_after_document_upload_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Path] = []

    def _ingest(_settings: object, path: Path, *, source_id: str) -> IngestResponse:
        seen.append(path)
        assert path.exists()
        raise DocumentUploadError("unreadable")

    monkeypatch.setattr(upload_mod, "ingest_uploaded_document", _ingest)
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.submit_uploaded_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        source_id="doc-1",
        session=session,
    )

    assert result.ok is False
    assert len(seen) == 1
    assert not seen[0].exists()


def test_temp_file_removed_after_unexpected_error_without_swallowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Path] = []

    def _ingest(_settings: object, path: Path, *, source_id: str) -> IngestResponse:
        seen.append(path)
        raise RuntimeError("disk failure")

    monkeypatch.setattr(upload_mod, "ingest_uploaded_document", _ingest)
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.submit_uploaded_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        source_id="doc-1",
        session=session,
    )

    assert result.ok is False
    assert "unexpectedly" in result.message.lower()
    assert "disk failure" not in result.message
    assert len(seen) == 1
    assert not seen[0].exists()


def test_unsupported_suffix_rejected_before_temp_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        upload_mod,
        "ingest_uploaded_document",
        lambda *a, **k: calls.append((a, k)),
    )
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.submit_uploaded_document(
        object(),
        filename="notes.docx",
        content=b"hello",
        source_id="doc-1",
        session=session,
    )

    assert result.ok is False
    assert "unsupported" in result.message.lower()
    assert calls == []
    assert session["ingest_in_progress"] is False


def test_success_message_includes_literal_accepted_and_chunk_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        upload_mod,
        "ingest_uploaded_document",
        lambda *_a, **_k: IngestResponse(accepted_ids=["doc-1"], chunk_count=3),
    )
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.submit_uploaded_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        source_id="doc-1",
        session=session,
    )

    assert result.ok is True
    assert "1" in result.message
    assert "3" in result.message


@pytest.mark.parametrize(
    ("error", "needle"),
    [
        (DocumentUploadError("bad upload"), "bad upload"),
        (DomainValidationError("blank id"), "blank id"),
        (ApplicationValidationError("bad request"), "bad request"),
        (ConfigurationError("missing key"), "missing key"),
    ],
)
def test_typed_failures_map_to_specific_messages(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    needle: str,
) -> None:
    def _ingest(*_a: object, **_k: object) -> IngestResponse:
        raise error

    monkeypatch.setattr(upload_mod, "ingest_uploaded_document", _ingest)
    session: dict[str, object] = {"ingest_in_progress": False}

    result = upload_mod.submit_uploaded_document(
        object(),
        filename="guide.txt",
        content=b"hello",
        source_id="doc-1",
        session=session,
    )

    assert result.ok is False
    assert needle in result.message


def test_unexpected_exception_is_logged_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _ingest(*_a: object, **_k: object) -> IngestResponse:
        raise RuntimeError("secret internals")

    monkeypatch.setattr(upload_mod, "ingest_uploaded_document", _ingest)
    session: dict[str, object] = {"ingest_in_progress": False}

    with caplog.at_level("ERROR"):
        result = upload_mod.submit_uploaded_document(
            object(),
            filename="guide.txt",
            content=b"hello",
            source_id="doc-1",
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
        assert "infrastructure.documents" not in module.__name__
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "infrastructure.documents" not in source
        assert "pypdf" not in source
        assert "extract_document" not in source
