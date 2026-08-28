"""JSON-file adapter for the uploaded-document catalog."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime
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


def _document_from_entry(entry: object, *, index: int) -> CatalogDocument:
    if not isinstance(entry, dict):
        raise CatalogValidationError(
            f"catalog entry {index} must be an object, got {type(entry).__name__}"
        )
    try:
        source_id = entry["source_id"]
        source_type_raw = entry["source_type"]
        file_name = entry["file_name"]
        status_raw = entry["status"]
        uploaded_at_raw = entry["uploaded_at"]
        chunk_count = entry["chunk_count"]
    except KeyError as error:
        raise CatalogValidationError(
            f"catalog entry {index} missing required field {error.args[0]!r}"
        ) from error
    try:
        source_type = SourceType(source_type_raw)
        status = CatalogStatus(status_raw)
        uploaded_at = datetime.fromisoformat(str(uploaded_at_raw))
        reference = SourceReference(str(source_id), source_type)
        return CatalogDocument(
            reference=reference,
            file_name=str(file_name),
            title=_optional_str(entry.get("title")),
            content_format=_optional_str(entry.get("content_format")),
            status=status,
            uploaded_at=uploaded_at,
            chunk_count=chunk_count,  # type: ignore[arg-type]
            error=_optional_str(entry.get("error")),
        )
    except (DomainValidationError, TypeError, ValueError) as error:
        raise CatalogValidationError(
            f"catalog entry {index} is invalid: {error}"
        ) from error


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
