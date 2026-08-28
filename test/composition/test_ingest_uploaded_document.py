"""Behavior tests for composition upload-to-ingest orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from composition import DocumentUploadError, ingest_uploaded_document
from composition import container as composition_container
from application.contracts import IngestRequest, IngestResponse
from domain.errors import DomainValidationError
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.config import Settings, load_settings
from infrastructure.documents.uploaded_files import (
    UnreadableDocumentError,
    UnsupportedDocumentError,
)


class _RecordingIngest:
    """Records the ingest request and returns a fixed response."""

    def __init__(self, response: IngestResponse) -> None:
        self.response = response
        self.calls: list[IngestRequest] = []

    def execute(self, request: IngestRequest) -> IngestResponse:
        self.calls.append(request)
        return self.response


@pytest.fixture
def chroma_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings pointed at `tmp_path`, with `.env` neutralized first."""
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    target = tmp_path / "chroma"
    monkeypatch.setenv("CHROMA_PERSIST_PATH", str(target))
    monkeypatch.setenv("CHROMA_COLLECTION", "kernector_knowledge")
    settings = load_settings()
    assert settings.chroma.persist_path == target
    return settings


@pytest.mark.parametrize("source_id", ["", "   ", "\n"])
def test_blank_source_id_raises_document_upload_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    chroma_settings: Settings,
    source_id: str,
) -> None:
    """Blank identity becomes DocumentUploadError before the ingest use case."""
    path = tmp_path / "guide.txt"
    path.write_text("hello", encoding="utf-8")
    calls: list[object] = []

    def _should_not_build(_settings: Settings) -> object:
        calls.append(_settings)
        raise AssertionError("build_ingest_knowledge must not run for blank source_id")

    monkeypatch.setattr(
        composition_container, "build_ingest_knowledge", _should_not_build
    )

    with pytest.raises(DocumentUploadError) as exc_info:
        ingest_uploaded_document(chroma_settings, path, source_id=source_id)

    assert str(exc_info.value).strip()
    assert isinstance(exc_info.value.__cause__, DomainValidationError)
    assert calls == []


@pytest.mark.parametrize(
    "error",
    [
        UnsupportedDocumentError("unsupported type"),
        UnreadableDocumentError("no extractable text"),
    ],
)
def test_extraction_failures_become_document_upload_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    chroma_settings: Settings,
    error: Exception,
) -> None:
    """Adapter extraction failures are translated before the ingest use case."""
    path = tmp_path / "guide.txt"
    path.write_text("hello", encoding="utf-8")
    calls: list[object] = []

    def _should_not_build(_settings: Settings) -> object:
        calls.append(_settings)
        raise AssertionError("build_ingest_knowledge must not run on extraction failure")

    monkeypatch.setattr(
        composition_container, "extract_document", lambda *_a, **_k: (_ for _ in ()).throw(error)
    )
    monkeypatch.setattr(
        composition_container, "build_ingest_knowledge", _should_not_build
    )

    with pytest.raises(DocumentUploadError, match=str(error)) as exc_info:
        ingest_uploaded_document(chroma_settings, path, source_id="doc-1")

    assert str(exc_info.value).strip()
    assert exc_info.value.__cause__ is error
    assert calls == []


def test_ingest_uploaded_document_executes_ingest_with_extracted_document(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    chroma_settings: Settings,
) -> None:
    """Composition extracts one document and returns the use-case response."""
    path = tmp_path / "guide.txt"
    path.write_text("hello world", encoding="utf-8")
    document = SourceDocument(
        SourceMetadata(
            SourceReference("upload-001", SourceType.KNOWLEDGE_DOCUMENT),
            title="guide",
            provider="upload",
            content_format="txt",
        ),
        "hello world",
    )
    expected = IngestResponse(accepted_ids=["upload-001"], chunk_count=2)
    recorder = _RecordingIngest(expected)

    monkeypatch.setattr(
        composition_container,
        "extract_document",
        lambda _path, *, source_id: document,
    )
    monkeypatch.setattr(
        composition_container,
        "build_ingest_knowledge",
        lambda _settings: recorder,
    )

    response = ingest_uploaded_document(
        chroma_settings, path, source_id="upload-001"
    )

    assert response is expected
    assert len(recorder.calls) == 1
    assert recorder.calls[0].documents == (document,)


def test_chroma_dimension_mismatch_becomes_document_upload_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    chroma_settings: Settings,
) -> None:
    """Store dimension mismatches surface as DocumentUploadError for the UI."""
    from infrastructure.vectorstore.chroma import ChromaStoreError

    path = tmp_path / "guide.txt"
    path.write_text("hello", encoding="utf-8")
    document = SourceDocument(
        SourceMetadata(
            SourceReference("upload-001", SourceType.KNOWLEDGE_DOCUMENT),
            title="guide",
            provider="upload",
            content_format="txt",
        ),
        "hello",
    )
    store_error = ChromaStoreError(
        "could not write 1 record(s) to collection 'kernector_knowledge': "
        "Collection expecting embedding with dimension of 3, got 4096"
    )

    class _FailingIngest:
        def execute(self, request: IngestRequest) -> IngestResponse:
            raise store_error

    monkeypatch.setattr(
        composition_container,
        "extract_document",
        lambda _path, *, source_id: document,
    )
    monkeypatch.setattr(
        composition_container,
        "build_ingest_knowledge",
        lambda _settings: _FailingIngest(),
    )

    with pytest.raises(DocumentUploadError, match="embedding size") as exc_info:
        ingest_uploaded_document(chroma_settings, path, source_id="upload-001")

    assert str(chroma_settings.chroma.persist_path) in str(exc_info.value)
    assert exc_info.value.__cause__ is store_error
