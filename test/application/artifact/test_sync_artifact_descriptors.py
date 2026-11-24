"""Descriptor sync hook: upsert, skip, remove, retry, extractor None (#373)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from application.artifact.sync import SyncArtifactDescriptors
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)


class _Extractor:
    def __init__(self, descriptor: ArtifactDescriptor | None) -> None:
        self._descriptor = descriptor
        self.calls = 0

    def describe(self, document: SourceDocument) -> ArtifactDescriptor | None:
        self.calls += 1
        return self._descriptor


class _Index:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.descriptors: dict[tuple[str, str], ArtifactDescriptor] = {}
        self.upserts = 0
        self.removes = 0
        self._fail_times = fail_times

    def upsert(self, descriptor: ArtifactDescriptor) -> None:
        self.upserts += 1
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError("index write failed")
        key = (descriptor.reference.source_type, descriptor.reference.source_id)
        self.descriptors[key] = descriptor

    def remove(self, reference: SourceReference) -> None:
        self.removes += 1
        self.descriptors.pop((reference.source_type, reference.source_id), None)

    def get(self, reference: SourceReference) -> ArtifactDescriptor | None:
        return self.descriptors.get((reference.source_type, reference.source_id))

    def find_by_key(self, keys: tuple[str, ...]) -> tuple[ArtifactDescriptor, ...]:
        return ()

    def list_for_scope(
        self, *, source_type: str | None = None
    ) -> tuple[ArtifactDescriptor, ...]:
        return ()


def _source(
    source_id: str = "file-1",
    *,
    source_type: str = SourceType.GOOGLE_DRIVE,
    revision_extra: str = "rev-meta",
) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            SourceReference(source_id, source_type),
            title="guide",
            extra={
                "drive_revision": revision_extra,
                "file_name": "guide.md",
            },
        ),
        "content body",
    )


def _descriptor_for(source: SourceDocument, *, revision: str = "rev-1") -> ArtifactDescriptor:
    return ArtifactDescriptor(
        reference=source.reference,
        revision=revision,
        kind=ArtifactKind.DOCUMENT,
        title=source.metadata.title,
    )


def test_upsert_stores_descriptor_with_connector_revision() -> None:
    source = _source()
    extracted = _descriptor_for(source, revision="from-extractor")
    index = _Index()
    sync = SyncArtifactDescriptors(_Extractor(extracted), index)

    sync.on_ready(source, revision="connector-rev")

    stored = index.get(source.reference)
    assert stored is not None
    assert stored.revision == "connector-rev"
    assert index.upserts == 1


def test_unchanged_skip_does_not_rewrite() -> None:
    source = _source()
    extracted = _descriptor_for(source)
    index = _Index()
    sync = SyncArtifactDescriptors(_Extractor(extracted), index)
    sync.on_ready(source, revision="r1")
    before = index.upserts

    sync.on_skipped(source.reference)

    assert index.upserts == before
    assert index.removes == 0


def test_remove_deletes_descriptor() -> None:
    source = _source()
    index = _Index()
    sync = SyncArtifactDescriptors(_Extractor(_descriptor_for(source)), index)
    sync.on_ready(source, revision="r1")

    sync.on_removed(source.reference)

    assert index.get(source.reference) is None
    assert index.removes == 1


def test_extractor_none_removes_stale_descriptor() -> None:
    source = _source()
    index = _Index()
    first = SyncArtifactDescriptors(_Extractor(_descriptor_for(source)), index)
    first.on_ready(source, revision="r1")
    assert index.get(source.reference) is not None

    SyncArtifactDescriptors(_Extractor(None), index).on_ready(source, revision="r2")

    assert index.get(source.reference) is None
    assert index.removes == 1


def test_index_write_is_retried_once() -> None:
    source = _source()
    index = _Index(fail_times=1)
    sync = SyncArtifactDescriptors(_Extractor(_descriptor_for(source)), index)

    sync.on_ready(source, revision="r1")

    assert index.get(source.reference) is not None
    assert index.upserts == 2


def test_index_write_failure_after_retry_raises() -> None:
    source = _source()
    index = _Index(fail_times=2)
    sync = SyncArtifactDescriptors(_Extractor(_descriptor_for(source)), index)

    with pytest.raises(RuntimeError, match="index write failed"):
        sync.on_ready(source, revision="r1")

    assert index.get(source.reference) is None
    assert index.upserts == 2
