"""In-memory and controllable doubles for document-management tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from domain.knowledge import (
    CatalogDocument,
    SourceDocument,
    SourceReference,
    UploadPayload,
)


class InMemoryDocumentCatalog:
    """Dict-backed DocumentCatalog for application tests."""

    def __init__(self) -> None:
        self._records: dict[SourceReference, CatalogDocument] = {}
        self.fail_on_upsert: bool = False
        self.fail_on_delete: bool = False

    def all(self) -> Sequence[CatalogDocument]:
        return tuple(self._records.values())

    def get(self, reference: SourceReference) -> CatalogDocument | None:
        return self._records.get(reference)

    def upsert(self, document: CatalogDocument) -> None:
        if self.fail_on_upsert:
            raise RuntimeError("catalog upsert failed")
        self._records[document.reference] = document

    def delete(self, reference: SourceReference) -> None:
        if self.fail_on_delete:
            raise RuntimeError("catalog delete failed")
        self._records.pop(reference, None)


class RecordingExtractor:
    """DocumentExtractor that returns a prepared document or raises."""

    def __init__(
        self,
        document_factory: Callable[[UploadPayload, SourceReference], SourceDocument]
        | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self._document_factory = document_factory
        self._error = error
        self.calls: list[tuple[UploadPayload, SourceReference]] = []

    def extract(
        self,
        payload: UploadPayload,
        *,
        reference: SourceReference,
    ) -> SourceDocument:
        self.calls.append((payload, reference))
        if self._error is not None:
            raise self._error
        if self._document_factory is None:
            raise AssertionError("no document factory configured")
        return self._document_factory(payload, reference)


class FixedIdFactory:
    """Deterministic source-id allocator for tests."""

    def __init__(self, *ids: str) -> None:
        self._ids = list(ids)
        self._index = 0

    def __call__(self) -> str:
        if self._index >= len(self._ids):
            raise AssertionError("FixedIdFactory exhausted")
        value = self._ids[self._index]
        self._index += 1
        return value


class FixedClock:
    """Deterministic timezone-aware clock for tests."""

    def __init__(self, *moments: datetime) -> None:
        if not moments:
            moments = (datetime(2026, 8, 28, 12, 0, tzinfo=UTC),)
        self._moments = list(moments)
        self._index = 0

    def __call__(self) -> datetime:
        if self._index >= len(self._moments):
            return self._moments[-1]
        value = self._moments[self._index]
        self._index += 1
        return value
