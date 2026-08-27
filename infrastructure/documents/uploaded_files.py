"""Turns one uploaded local file into a `SourceDocument`.

`extract_document` is the whole public seam: TXT, Markdown, or a text-based PDF
becomes a normalized domain document that any consumer (chunking, ingestion) can
take without knowing where it came from. Identity is always supplied by the
caller — never derived from the file name, path, or content.

PDF text extraction is verified against pypdf 6.16.2, whose `PyPdfError` base
covers the read failures this adapter normalizes (`PdfStreamError` for a corrupt
file, `FileNotDecryptedError` for an encrypted one). There is no OCR: a
scanned, image-only PDF has no text layer and is reported as unreadable.
"""

from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)

_PROVIDER = "upload"
_PDF = "pdf"

# Suffix -> canonical `content_format`. Consumers group by the format, not by the
# suffix, so `.md` and `.markdown` deliberately collapse onto one value.
_FORMAT_BY_SUFFIX = {
    ".txt": "txt",
    ".md": "markdown",
    ".markdown": "markdown",
    ".pdf": _PDF,
}

# Derived, never maintained by hand: one map is the single source of truth for
# both what is accepted and what `content_format` it becomes.
SUPPORTED_SUFFIXES: frozenset[str] = frozenset(_FORMAT_BY_SUFFIX)

# Separator between extracted PDF pages: a blank line, as between paragraphs.
_PAGE_SEPARATOR = "\n\n"


class DocumentExtractionError(RuntimeError):
    """The uploaded-file adapter could not produce a SourceDocument."""


class UnsupportedDocumentError(DocumentExtractionError):
    """The file type is outside TXT, Markdown, and text-based PDF."""


class UnreadableDocumentError(DocumentExtractionError):
    """The file could not be read or yielded no extractable text."""


def _extract_pdf(path: Path) -> tuple[str, int]:
    """Read a PDF's text layer and its page count.

    pypdf ends each page's text with a newline of its own, so page text is
    stripped before joining; otherwise the separator would grow by one line per
    page. Pages with no text layer contribute nothing rather than an empty gap,
    but they still count: the page count describes the file, not the text.

    Args:
        path (Path): PDF file to read.

    Returns:
        tuple[str, int]: The joined page text, and the number of pages.
    """
    reader = PdfReader(path)
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    return _PAGE_SEPARATOR.join(page for page in pages if page), len(pages)


def extract_document(path: Path, *, source_id: str) -> SourceDocument:
    """Normalize one supported local file into a SourceDocument.

    Args:
        path (Path): Local file to read.
        source_id (str): Caller-supplied source identity. Never derived from the
            file name, path, or content.

    Returns:
        SourceDocument: The file's text with its provenance metadata.

    Raises:
        DomainValidationError: If `source_id` is blank.
        UnsupportedDocumentError: If the suffix is outside the supported set.
        UnreadableDocumentError: If the file cannot be read, or holds no
            extractable text.
    """
    # Identity first: a caller contract violation must fail without any I/O.
    reference = SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)
    suffix = path.suffix.lower()
    if suffix not in _FORMAT_BY_SUFFIX:
        described = repr(suffix) if suffix else "no suffix"
        raise UnsupportedDocumentError(
            f"{path}: unsupported document type ({described}); supported types "
            f"are {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )
    content_format = _FORMAT_BY_SUFFIX[suffix]
    page_count: int | None = None
    try:
        if content_format == _PDF:
            text, page_count = _extract_pdf(path)
        else:
            text = path.read_text(encoding="utf-8")
        stat = path.stat()
    except (OSError, UnicodeDecodeError, PyPdfError) as exc:
        raise UnreadableDocumentError(f"{path}: could not be read: {exc}") from exc
    if not text.strip():
        raise UnreadableDocumentError(f"{path}: no extractable text")
    extra = {
        "file_name": path.name,
        "byte_size": str(stat.st_size),
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }
    if page_count is not None:
        extra["page_count"] = str(page_count)
    return SourceDocument(
        SourceMetadata(
            reference,
            title=path.stem,
            provider=_PROVIDER,
            content_format=content_format,
            extra=extra,
        ),
        text,
    )
