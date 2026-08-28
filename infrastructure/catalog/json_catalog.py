"""JSON-file adapter for the uploaded-document catalog."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from domain.errors import DomainValidationError
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceReference,
    SourceType,
)


class CatalogError(RuntimeError):
    """Base error raised by the JSON document catalog adapter."""


class CatalogParseError(CatalogError):
    """The catalog file cannot be decoded as JSON."""


class CatalogValidationError(CatalogError):
    """Parsed JSON violates the catalog contract."""


class JsonDocumentCatalog:
    """Persist catalog rows as a JSON array with atomic replace writes.

    Every read reloads from disk. A process-wide lock keyed by the resolved
    catalog path covers each read-modify-write so concurrent Streamlit threads
    do not lose updates. Simultaneous multi-process writers are unsupported.
    """

    _locks: ClassVar[dict[str, threading.Lock]] = {}
    _locks_guard: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, path: Path) -> None:
        """Create an adapter bound to ``path``.

        Args:
            path (Path): Durable JSON catalog location. Parent directories are
                created only when writing.
        """
        self._path = path

    def all(self) -> Sequence[CatalogDocument]:
        """Return every catalog record from durable storage."""
        with self._lock():
            return tuple(self._load_unlocked().values())

    def get(self, reference: SourceReference) -> CatalogDocument | None:
        """Return the record for ``reference``, or ``None`` when absent."""
        with self._lock():
            return self._load_unlocked().get(reference)

    def upsert(self, document: CatalogDocument) -> None:
        """Insert or replace the record keyed by ``document.reference``."""
        with self._lock():
            records = self._load_unlocked()
            records[document.reference] = document
            self._write_unlocked(records)

    def delete(self, reference: SourceReference) -> None:
        """Remove the record for ``reference``. Missing references are a no-op."""
        with self._lock():
            records = self._load_unlocked()
            if reference not in records:
                return
            del records[reference]
            self._write_unlocked(records)

    def _lock(self) -> threading.Lock:
        key = str(self._path.resolve())
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def _load_unlocked(self) -> dict[SourceReference, CatalogDocument]:
        if not self._path.exists():
            return {}
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError as error:
            raise CatalogError(f"could not read catalog at {self._path}") from error
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise CatalogParseError(
                f"catalog at {self._path} is not valid JSON"
            ) from error
        if not isinstance(payload, list):
            raise CatalogValidationError(
                f"catalog root must be a JSON array, got {type(payload).__name__}"
            )
        records: dict[SourceReference, CatalogDocument] = {}
        for index, entry in enumerate(payload):
            document = _document_from_entry(entry, index=index)
            if document.reference in records:
                # Refusing beats last-one-wins: the next write serializes this
                # dict, so silently collapsing the pair would delete a row from
                # disk and orphan its chunks with nothing left pointing at them.
                reference = document.reference
                raise CatalogValidationError(
                    f"catalog entry {index} duplicates source "
                    f"{reference.source_type.value}:{reference.source_id}; "
                    "each source may appear at most once"
                )
            records[document.reference] = document
        return records

    def _write_unlocked(
        self, records: Mapping[SourceReference, CatalogDocument]
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [_entry_from_document(document) for document in records.values()]
        temporary = self._path.with_name(f".{self._path.name}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise CatalogError(f"could not write catalog at {self._path}") from error


def _entry_from_document(document: CatalogDocument) -> dict[str, object]:
    return {
        "source_id": document.reference.source_id,
        "source_type": document.reference.source_type.value,
        "file_name": document.file_name,
        "title": document.title,
        "content_format": document.content_format,
        "status": document.status.value,
        "uploaded_at": document.uploaded_at.isoformat(),
        "chunk_count": document.chunk_count,
        "error": document.error,
    }


# Declaration order, so a hand-edited file is reported field by field from the
# top rather than in whatever order a dict happens to iterate.
_REQUIRED_FIELDS = (
    "source_id",
    "source_type",
    "file_name",
    "status",
    "uploaded_at",
    "chunk_count",
)


def _document_from_entry(entry: object, *, index: int) -> CatalogDocument:
    """Build one catalog row, rejecting anything the writer would not have made.

    Types are checked, never coerced. ``str(value)`` would turn an integer
    ``source_id`` into a plausible string that keys real vector chunks, so the
    corruption would survive the next write instead of being caught on read —
    and a wrong ``chunk_count`` would silently claim a document has content it
    does not have.

    Raises:
        CatalogValidationError: A field is missing or holds the wrong type. The
            message names the entry index and the offending field.
    """
    if not isinstance(entry, dict):
        raise CatalogValidationError(
            f"catalog entry {index} must be an object, got {type(entry).__name__}"
        )
    for field in _REQUIRED_FIELDS:
        if field not in entry:
            raise CatalogValidationError(
                f"catalog entry {index} missing required field {field!r}"
            )
    source_id = _require_str(entry, "source_id", index=index)
    file_name = _require_str(entry, "file_name", index=index)
    source_type = _require_member(
        SourceType, _require_str(entry, "source_type", index=index),
        field="source_type", index=index,
    )
    status = _require_member(
        CatalogStatus, _require_str(entry, "status", index=index),
        field="status", index=index,
    )
    uploaded_at_raw = _require_str(entry, "uploaded_at", index=index)
    try:
        uploaded_at = datetime.fromisoformat(uploaded_at_raw)
    except ValueError as error:
        raise CatalogValidationError(
            f"catalog entry {index} field 'uploaded_at' is not an ISO-8601 "
            f"timestamp: {uploaded_at_raw!r}"
        ) from error
    try:
        return CatalogDocument(
            reference=SourceReference(source_id, source_type),
            file_name=file_name,
            title=_optional_str(entry, "title", index=index),
            content_format=_optional_str(entry, "content_format", index=index),
            status=status,
            uploaded_at=uploaded_at,
            chunk_count=_require_int(entry, "chunk_count", index=index),
            error=_optional_str(entry, "error", index=index),
        )
    except DomainValidationError as error:
        # Domain invariants the JSON types cannot express: blank text, a
        # negative count, a naive timestamp. Its messages already name the field.
        raise CatalogValidationError(
            f"catalog entry {index} is invalid: {error}"
        ) from error


def _require_str(entry: Mapping[str, object], field: str, *, index: int) -> str:
    value = entry[field]
    if not isinstance(value, str):
        raise CatalogValidationError(
            f"catalog entry {index} field {field!r} must be a string, got "
            f"{type(value).__name__}"
        )
    return value


def _require_int(entry: Mapping[str, object], field: str, *, index: int) -> int:
    value = entry[field]
    # `bool` is an `int` subclass, so `True` would otherwise be read as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise CatalogValidationError(
            f"catalog entry {index} field {field!r} must be an integer, got "
            f"{type(value).__name__}"
        )
    return value


def _optional_str(
    entry: Mapping[str, object], field: str, *, index: int
) -> str | None:
    value = entry.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise CatalogValidationError(
            f"catalog entry {index} field {field!r} must be a string or null, "
            f"got {type(value).__name__}"
        )
    return value


def _require_member[MemberT: StrEnum](
    enum: type[MemberT], raw: str, *, field: str, index: int
) -> MemberT:
    try:
        return enum(raw)
    except ValueError as error:
        allowed = ", ".join(sorted(member.value for member in enum))
        raise CatalogValidationError(
            f"catalog entry {index} field {field!r} must be one of {allowed}; "
            f"got {raw!r}"
        ) from error
