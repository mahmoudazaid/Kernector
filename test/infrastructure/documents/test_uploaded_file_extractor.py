"""Tests for the upload-payload document extractor adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.knowledge import SourceReference, SourceType, UploadPayload
from infrastructure.documents.uploaded_files import (
    UnreadableDocumentError,
    UnsupportedDocumentError,
    UploadedFileExtractor,
)


def _reference(source_id: str = "upload-1") -> SourceReference:
    return SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)


def test_extract_propagates_real_file_name_and_title() -> None:
    extractor = UploadedFileExtractor()
    document = extractor.extract(
        UploadPayload(file_name="product-guide.md", content=b"# Product guide\n"),
        reference=_reference("id-42"),
    )
    assert document.source_id == "id-42"
    assert document.metadata.title == "product-guide"
    assert document.metadata.content_format == "markdown"
    assert document.metadata.extra["file_name"] == "product-guide.md"
    assert "Product guide" in document.content


def test_extract_sanitizes_path_like_client_names() -> None:
    extractor = UploadedFileExtractor()
    document = extractor.extract(
        UploadPayload(
            file_name="../secrets/../../guide.md",
            content=b"# Safe\n",
        ),
        reference=_reference(),
    )
    assert document.metadata.extra["file_name"] == "guide.md"
    assert document.metadata.title == "guide"


def test_extract_rejects_unsupported_type() -> None:
    extractor = UploadedFileExtractor()
    with pytest.raises(UnsupportedDocumentError):
        extractor.extract(
            UploadPayload(file_name="notes.docx", content=b"x"),
            reference=_reference(),
        )


def test_extract_rejects_empty_text() -> None:
    extractor = UploadedFileExtractor()
    with pytest.raises(UnreadableDocumentError):
        extractor.extract(
            UploadPayload(file_name="empty.md", content=b"   \n"),
            reference=_reference(),
        )


def test_extract_cleans_up_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Temp directories created during extract must not linger after success."""
    created: list[Path] = []
    real_temporary_directory = __import__("tempfile").TemporaryDirectory

    class TrackingTemporaryDirectory(real_temporary_directory):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            created.append(Path(self.name))

    monkeypatch.setattr(
        "infrastructure.documents.uploaded_files.TemporaryDirectory",
        TrackingTemporaryDirectory,
    )
    extractor = UploadedFileExtractor()
    extractor.extract(
        UploadPayload(file_name="guide.md", content=b"# Hi\n"),
        reference=_reference(),
    )
    assert created
    assert all(not path.exists() for path in created)


def test_extract_cleans_up_temporary_files_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[Path] = []
    real_temporary_directory = __import__("tempfile").TemporaryDirectory

    class TrackingTemporaryDirectory(real_temporary_directory):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            created.append(Path(self.name))

    monkeypatch.setattr(
        "infrastructure.documents.uploaded_files.TemporaryDirectory",
        TrackingTemporaryDirectory,
    )
    extractor = UploadedFileExtractor()
    with pytest.raises(UnreadableDocumentError):
        extractor.extract(
            UploadPayload(file_name="empty.md", content=b"   \n"),
            reference=_reference(),
        )
    assert created
    assert all(not path.exists() for path in created)


def test_unsupported_type_is_rejected_before_any_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected upload must never be written to disk, however large it is."""
    created: list[Path] = []
    real_temporary_directory = __import__("tempfile").TemporaryDirectory

    class TrackingTemporaryDirectory(real_temporary_directory):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            created.append(Path(self.name))

    monkeypatch.setattr(
        "infrastructure.documents.uploaded_files.TemporaryDirectory",
        TrackingTemporaryDirectory,
    )
    extractor = UploadedFileExtractor()
    with pytest.raises(UnsupportedDocumentError):
        extractor.extract(
            UploadPayload(file_name="notes.docx", content=b"x" * 1024),
            reference=_reference(),
        )
    assert created == []


def test_extract_carries_the_callers_source_type() -> None:
    """Chunks are stored under the whole reference, so the kind must survive."""
    extractor = UploadedFileExtractor()
    reference = SourceReference("id-9", "connector_feed")
    document = extractor.extract(
        UploadPayload(file_name="guide.md", content=b"# Guide\n"),
        reference=reference,
    )
    assert document.metadata.reference == reference
    assert document.metadata.reference.source_type == "connector_feed"
