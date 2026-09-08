"""Unit tests for provider-neutral connector document contracts."""

import pytest

from domain.errors import DomainValidationError
from domain.knowledge import ConnectorDocument, SourceReference, SourceType

BLANK = ["", "   ", "\n"]


def _reference(source_id: str = "drive-file-1") -> SourceReference:
    return SourceReference(source_id, SourceType.GOOGLE_DRIVE)


def test_valid_connector_document_is_accepted() -> None:
    extra = {"mime_type": "text/plain"}
    document = ConnectorDocument(
        reference=_reference(),
        file_name="notes.txt",
        revision="42",
        extra=extra,
    )
    assert document.reference.source_id == "drive-file-1"
    assert document.file_name == "notes.txt"
    assert document.revision == "42"
    assert document.extra == extra
    assert document.source_id == "drive-file-1"


def test_connector_document_source_id_projects_from_reference() -> None:
    document = ConnectorDocument(
        reference=_reference("file-abc"),
        file_name="guide.md",
        revision="7",
    )
    assert document.source_id == "file-abc"


def test_connector_document_extra_defaults_empty() -> None:
    document = ConnectorDocument(
        reference=_reference(),
        file_name="guide.md",
        revision="1",
    )
    assert document.extra == {}


def test_connector_document_rejects_non_reference() -> None:
    with pytest.raises(DomainValidationError, match="reference"):
        ConnectorDocument(
            reference="file-1",  # type: ignore[arg-type]
            file_name="guide.md",
            revision="1",
        )


@pytest.mark.parametrize("blank", BLANK)
def test_connector_document_rejects_blank_file_name(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="file_name"):
        ConnectorDocument(
            reference=_reference(),
            file_name=blank,
            revision="1",
        )


@pytest.mark.parametrize("blank", BLANK)
def test_connector_document_rejects_blank_revision(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="revision"):
        ConnectorDocument(
            reference=_reference(),
            file_name="guide.md",
            revision=blank,
        )


def test_source_type_includes_google_drive() -> None:
    assert SourceType.GOOGLE_DRIVE == "google_drive"
