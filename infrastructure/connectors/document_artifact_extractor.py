"""Google Drive and upload sources → document ArtifactDescriptor."""

from __future__ import annotations

from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor
from domain.knowledge import SourceDocument, SourceType

_DOCUMENT_SOURCE_TYPES = frozenset(
    {SourceType.GOOGLE_DRIVE, SourceType.KNOWLEDGE_DOCUMENT}
)


class DocumentArtifactDescriptorExtractor:
    """Treat Drive files and knowledge uploads as document artifacts."""

    def describe(self, document: SourceDocument) -> ArtifactDescriptor | None:
        if document.reference.source_type not in _DOCUMENT_SOURCE_TYPES:
            return None
        extra = document.metadata.extra
        revision = (
            extra.get("drive_revision")
            or extra.get("content_fingerprint")
            or extra.get("revision")
        )
        if not isinstance(revision, str) or not revision.strip():
            return None
        return ArtifactDescriptor(
            reference=document.reference,
            revision=revision.strip(),
            kind=ArtifactKind.DOCUMENT,
            external_keys=(),
            title=document.metadata.title,
        )
