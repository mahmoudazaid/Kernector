"""Loads a JSON knowledge corpus into normalized domain documents.

`load_knowledge_corpus` is the public seam: a JSON array of corpus records
becomes a tuple of `SourceDocument` values that ingestion can consume without
knowing the on-disk format. Concrete categories stay in
`SourceMetadata.extra["doc_type"]`; every record uses
`SourceType.KNOWLEDGE_DOCUMENT`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)

_IDENTITY_FIELDS = frozenset({"source_id", "title", "content"})
_REQUIRED_FIELDS = (
    "source_id",
    "title",
    "doc_type",
    "content",
    "status",
    "version",
)


class CorpusLoadError(RuntimeError):
    """Base error raised while loading a knowledge corpus."""


class CorpusNotFoundError(CorpusLoadError):
    """The configured corpus file does not exist."""


class CorpusParseError(CorpusLoadError):
    """The corpus cannot be decoded or parsed as JSON."""


class CorpusValidationError(CorpusLoadError):
    """Parsed JSON violates the generic corpus contract."""


def load_knowledge_corpus(path: Path) -> tuple[SourceDocument, ...]:
    """Load and normalize every record in a JSON knowledge corpus.

    Args:
        path (Path): Absolute or relative path to a JSON array of corpus records.

    Returns:
        tuple[SourceDocument, ...]: One normalized document per corpus record.

    Raises:
        CorpusNotFoundError: If ``path`` does not exist.
        CorpusParseError: If the file is not valid UTF-8 JSON.
        CorpusValidationError: If the payload violates the corpus contract.
        CorpusLoadError: If the file cannot be read for another OS reason.
    """
    text = _read_corpus_text(path)
    payload = _parse_corpus_json(text)
    if not isinstance(payload, list):
        raise CorpusValidationError(
            f"knowledge corpus root must be a JSON array, got {type(payload).__name__}"
        )
    records = [
        _require_record(entry, index) for index, entry in enumerate(payload)
    ]
    _require_unique_source_ids(records)
    return tuple(
        _document_from_record(record, index=index)
        for index, record in enumerate(records)
    )


def _read_corpus_text(path: Path) -> str:
    """Read corpus file bytes as UTF-8 text, mapping OS failures to typed errors."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise CorpusNotFoundError(f"knowledge corpus not found: {path}") from error
    except UnicodeDecodeError as error:
        raise CorpusParseError(
            f"knowledge corpus is not valid UTF-8: {path}"
        ) from error
    except OSError as error:
        raise CorpusLoadError(f"knowledge corpus unreadable: {path}") from error


def _parse_corpus_json(text: str) -> object:
    """Decode JSON text, mapping decode failures to CorpusParseError."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise CorpusParseError("knowledge corpus is not valid JSON") from error


def _require_record(value: object, index: int) -> Mapping[str, object]:
    """Reject non-object entries and missing/blank required fields."""
    if not isinstance(value, dict):
        raise CorpusValidationError(
            f"record {index} must be an object, got {type(value).__name__}"
        )
    for field_name in _REQUIRED_FIELDS:
        _require_non_blank_string(value, field_name, index)
    return value


def _require_non_blank_string(
    record: Mapping[str, object], field_name: str, index: int
) -> str:
    """Require a non-blank string field on one corpus record."""
    if field_name not in record:
        raise CorpusValidationError(
            f"record {index} missing required field {field_name!r}"
        )
    value = record[field_name]
    if not isinstance(value, str) or not value.strip():
        raise CorpusValidationError(
            f"record {index} field {field_name!r} must be a non-blank string, "
            f"got {value!r}"
        )
    return value


def _require_unique_source_ids(records: list[Mapping[str, object]]) -> None:
    """Reject duplicate source_id values with an exact, case-sensitive match."""
    seen: dict[str, int] = {}
    for index, record in enumerate(records):
        source_id = str(record["source_id"])
        if source_id in seen:
            raise CorpusValidationError(
                f"record {index} duplicates source_id {source_id!r} "
                f"from record {seen[source_id]}"
            )
        seen[source_id] = index


def _document_from_record(
    record: Mapping[str, object], *, index: int
) -> SourceDocument:
    """Map one validated corpus object into a SourceDocument."""
    return SourceDocument(
        metadata=SourceMetadata(
            reference=SourceReference(
                str(record["source_id"]),
                SourceType.KNOWLEDGE_DOCUMENT,
            ),
            title=str(record["title"]),
            extra=_extra_from_record(record, index=index),
        ),
        content=str(record["content"]),
    )


def _extra_from_record(
    record: Mapping[str, object], *, index: int
) -> dict[str, str]:
    """Build string-only extras: omit nulls, serialize arrays, reject objects."""
    extra: dict[str, str] = {}
    for key, value in record.items():
        if key in _IDENTITY_FIELDS or value is None:
            continue
        if isinstance(value, dict):
            raise CorpusValidationError(
                f"record {index} field {key!r} must not be a nested object"
            )
        if isinstance(value, list):
            extra[f"{key}_json"] = json.dumps(
                value, separators=(",", ":"), ensure_ascii=False
            )
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise CorpusValidationError(
                f"record {index} field {key!r} has unsupported type "
                f"{type(value).__name__}"
            )
        extra[key] = value if isinstance(value, str) else str(value)
    return extra
