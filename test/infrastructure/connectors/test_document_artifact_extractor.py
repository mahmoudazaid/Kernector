"""Drive and upload document artifact descriptors (#373)."""

from __future__ import annotations

from domain.artifact.kinds import ArtifactKind
from domain.knowledge import SourceDocument, SourceMetadata, SourceReference, SourceType
from infrastructure.connectors.document_artifact_extractor import (
    DocumentArtifactDescriptorExtractor,
)


def test_google_drive_file_is_document() -> None:
    extractor = DocumentArtifactDescriptorExtractor()
    document = SourceDocument(
        SourceMetadata(
            reference=SourceReference("drive-file-1", SourceType.GOOGLE_DRIVE),
            title="Orders overview",
            provider="google_drive",
            content_format="markdown",
            extra={
                "drive_file_id": "drive-file-1",
                "drive_revision": "42",
                "file_name": "orders.md",
            },
        ),
        "# Orders\n",
    )

    descriptor = extractor.describe(document)

    assert descriptor is not None
    assert descriptor.kind == ArtifactKind.DOCUMENT
    assert descriptor.revision == "42"
    assert descriptor.external_keys == ()


def test_upload_is_document() -> None:
    extractor = DocumentArtifactDescriptorExtractor()
    document = SourceDocument(
        SourceMetadata(
            reference=SourceReference("upload-1", SourceType.KNOWLEDGE_DOCUMENT),
            title="notes.md",
            provider="upload",
            content_format="markdown",
            extra={"content_fingerprint": "fp-1", "file_name": "notes.md"},
        ),
        "notes\n",
    )

    descriptor = extractor.describe(document)

    assert descriptor is not None
    assert descriptor.kind == ArtifactKind.DOCUMENT
    assert descriptor.revision == "fp-1"


def test_jira_document_returns_none() -> None:
    extractor = DocumentArtifactDescriptorExtractor()
    document = SourceDocument(
        SourceMetadata(
            reference=SourceReference("cloud/PROJ:PROJ-1", SourceType.JIRA),
            title="PROJ-1",
            extra={"jira_issue_key": "PROJ-1", "jira_updated_at": "r"},
        ),
        "body",
    )

    assert extractor.describe(document) is None
