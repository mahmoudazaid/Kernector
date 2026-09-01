"""Split SourceDocument content into indexed DocumentChunk windows."""

from __future__ import annotations

import re

from application.errors import ApplicationValidationError
from domain.knowledge import DocumentChunk, SourceDocument

_ORDERED_LIST = re.compile(r"^\s*\d+\.\s")
_TABLE_SEPARATOR = re.compile(r"^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")


def chunk_document(
    document: SourceDocument,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> tuple[DocumentChunk, ...]:
    """Split *document* into retrievable chunks.

    Markdown sources (``content_format == "markdown"``) are split on structure
    so table rows, headings, lists, and fenced code blocks stay intact when
    possible. All other formats use overlapping character windows.

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
        return (DocumentChunk(document.metadata, 0, text),)

    if document.metadata.content_format == "markdown":
        pieces = _chunk_markdown_text(text, chunk_size, chunk_overlap)
    else:
        pieces = _chunk_character_windows(text, chunk_size, chunk_overlap)

    chunks = tuple(
        DocumentChunk(document.metadata, index, piece)
        for index, piece in enumerate(pieces)
        if piece.strip()
    )
    if not chunks:
        raise ApplicationValidationError(
            "document content produced no non-blank chunks"
        )
    return chunks


def _chunk_markdown_text(
    text: str, chunk_size: int, chunk_overlap: int
) -> list[str]:
    blocks = _parse_markdown_blocks(text)
    packed: list[str] = []
    current = ""

    for block in blocks:
        if not block:
            continue
        if not current:
            added = _pack_block(block, chunk_size, chunk_overlap, packed)
            current = added
            continue

        separator = "\n\n" if not current.endswith("\n") else "\n"
        candidate = current + separator + block
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current.strip():
            packed.append(current)
        added = _pack_block(block, chunk_size, chunk_overlap, packed)
        current = added

    if current.strip():
        packed.append(current)
    return packed


def _pack_block(
    block: str,
    chunk_size: int,
    chunk_overlap: int,
    packed: list[str],
) -> str:
    if len(block) <= chunk_size:
        return block
    if _is_table_block(block):
        table_pieces = _split_table_block(block, chunk_size, chunk_overlap)
        if len(table_pieces) == 1:
            return table_pieces[0]
        packed.extend(table_pieces[:-1])
        return table_pieces[-1]
    pieces = _chunk_character_windows(block, chunk_size, chunk_overlap)
    if len(pieces) == 1:
        return pieces[0]
    packed.extend(pieces[:-1])
    return pieces[-1]


def _parse_markdown_blocks(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        if stripped.startswith("```"):
            block, index = _read_fenced_block(lines, index)
            blocks.append(block)
            continue

        if stripped.startswith("|"):
            block, index = _read_table_block(lines, index)
            blocks.append(block)
            continue

        if line.lstrip().startswith("#"):
            blocks.append(line)
            index += 1
            continue

        if _is_list_item(line):
            block, index = _read_list_block(lines, index)
            blocks.append(block)
            continue

        block, index = _read_paragraph_block(lines, index)
        blocks.append(block)

    return blocks


def _read_fenced_block(lines: list[str], start: int) -> tuple[str, int]:
    block = lines[start]
    index = start + 1
    while index < len(lines):
        block += lines[index]
        if lines[index].strip().startswith("```") and index > start:
            return block, index + 1
        index += 1
    return block, index


def _read_table_block(lines: list[str], start: int) -> tuple[str, int]:
    block = lines[start]
    index = start + 1
    while index < len(lines) and lines[index].strip().startswith("|"):
        block += lines[index]
        index += 1
    return block, index


def _read_list_block(lines: list[str], start: int) -> tuple[str, int]:
    block = lines[start]
    index = start + 1
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            break
        if _is_list_item(line) or line[:1] in {" ", "\t"}:
            block += line
            index += 1
            continue
        break
    return block, index


def _read_paragraph_block(lines: list[str], start: int) -> tuple[str, int]:
    block = lines[start]
    index = start + 1
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            break
        if _starts_structural_line(line):
            break
        block += line
        index += 1
    return block, index


def _starts_structural_line(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith("```")
        or stripped.startswith("|")
        or line.lstrip().startswith("#")
        or _is_list_item(line)
    )


def _is_list_item(line: str) -> bool:
    stripped = line.lstrip()
    return (
        stripped.startswith(("-", "*", "+"))
        or bool(_ORDERED_LIST.match(stripped))
    )


def _is_table_block(text: str) -> bool:
    first = text.splitlines()[0].strip()
    return first.startswith("|")


def _split_table_block(
    table: str, chunk_size: int, chunk_overlap: int
) -> list[str]:
    lines = table.splitlines(keepends=True)
    if not lines:
        return _chunk_character_windows(table, chunk_size, chunk_overlap)

    header = lines[0]
    separator = ""
    data_start = 1
    if len(lines) > 1 and _TABLE_SEPARATOR.match(lines[1].strip()):
        separator = lines[1]
        data_start = 2

    prefix = header + separator
    data_rows = lines[data_start:]
    if not data_rows:
        return [table] if len(table) <= chunk_size else _chunk_character_windows(
            table, chunk_size, chunk_overlap
        )

    if len(prefix + data_rows[0]) > chunk_size:
        return _chunk_character_windows(table, chunk_size, chunk_overlap)

    chunks: list[str] = []
    current = prefix
    for row in data_rows:
        candidate = current + row
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current.strip() and current != prefix:
            chunks.append(current.rstrip("\n"))
        current = prefix + row
        if len(current) > chunk_size:
            return _chunk_character_windows(table, chunk_size, chunk_overlap)

    if current.strip():
        chunks.append(current.rstrip("\n"))
    return chunks or _chunk_character_windows(table, chunk_size, chunk_overlap)


def _chunk_character_windows(
    text: str, chunk_size: int, chunk_overlap: int
) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    step = chunk_size - chunk_overlap
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        window = text[start:end]
        if window.strip():
            chunks.append(window)
        if end >= len(text):
            break
        start += step
    return chunks


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
