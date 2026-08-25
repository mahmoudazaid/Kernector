"""Split SourceDocument content into indexed DocumentChunk windows."""

from application.errors import ApplicationValidationError
from domain.knowledge import DocumentChunk, SourceDocument


def chunk_document(
    document: SourceDocument,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> tuple[DocumentChunk, ...]:
    """Split *document* into overlapping character windows.

    Args:
        document: Any valid SourceDocument (origin-agnostic).
        chunk_size: Max characters per chunk; must be > 0.
        chunk_overlap: Overlap with the previous chunk; must satisfy
            ``0 <= chunk_overlap < chunk_size``.

    Returns:
        Contiguously indexed DocumentChunk values that reuse
        ``document.metadata`` unchanged.

    Raises:
        ApplicationValidationError: Invalid document or chunk settings.
    """
    if not isinstance(document, SourceDocument):
        raise ApplicationValidationError(
            f"document must be a SourceDocument, got {document!r}"
        )
    _require_chunk_setting(chunk_size, "chunk_size")
    _require_chunk_setting(chunk_overlap, "chunk_overlap", allow_zero=True)
    if chunk_overlap >= chunk_size:
        raise ApplicationValidationError(
            "chunk_overlap must be < chunk_size, "
            f"got overlap={chunk_overlap}, size={chunk_size}"
        )

    text = document.content
    if len(text) <= chunk_size:
        return (
            DocumentChunk(document.metadata, 0, text),
        )

    step = chunk_size - chunk_overlap
    chunks: list[DocumentChunk] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        window = text[start:end]
        if window.strip():  # DocumentChunk rejects blank content
            chunks.append(DocumentChunk(document.metadata, index, window))
            index += 1
        if end >= len(text):
            break
        start += step

    if not chunks:
        raise ApplicationValidationError(
            "document content produced no non-blank chunks"
        )
    return tuple(chunks)


def _require_chunk_setting(
    value: object, name: str, *, allow_zero: bool = False
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApplicationValidationError(
            f"{name} must be an integer, got {value!r}"
        )
    if allow_zero:
        if value < 0:
            raise ApplicationValidationError(
                f"{name} must be >= 0, got {value}"
            )
    elif value <= 0:
        raise ApplicationValidationError(
            f"{name} must be > 0, got {value}"
        )