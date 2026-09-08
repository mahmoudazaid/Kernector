"""Connector synchronization: skip, replace, isolate failures, recover catalog."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from application.contracts import (
    ConnectorSyncStatus,
    IngestRequest,
    IngestResponse,
)
from application.ingest_knowledge import IngestFailure, IngestKnowledge
from application.sync_connector import SyncConnectorDocuments
from domain.errors import ConnectorAuthError, ConnectorError
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    ConnectorDocument,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from test.document_doubles import FixedClock, InMemoryDocumentCatalog
from test.doubles import InMemoryVectorStore, StubEmbeddingModel
from test.log_record import flatten_log_record, operation_records

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
CONTENT = "abcdefghijklmnopqrstuvwxyz"
SECRET = "DRIVE-SECRET-TOKEN-LEAK"


def _reference(source_id: str = "file-1") -> SourceReference:
    return SourceReference(source_id, SourceType.GOOGLE_DRIVE)


def _listed(
    source_id: str = "file-1",
    *,
    file_name: str = "guide.md",
    revision: str = "1",
) -> ConnectorDocument:
    return ConnectorDocument(
        reference=_reference(source_id),
        file_name=file_name,
        revision=revision,
    )


def _source(
    document: ConnectorDocument,
    *,
    content: str = CONTENT,
) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            document.reference,
            title=document.file_name.rsplit(".", 1)[0],
            provider="google_drive",
            content_format="markdown",
            extra={"file_name": document.file_name},
        ),
        content,
    )


def _row(
    document: ConnectorDocument,
    *,
    status: CatalogStatus = CatalogStatus.READY,
    chunk_count: int = 3,
    revision: str | None = "1",
    error: str | None = None,
) -> CatalogDocument:
    return CatalogDocument(
        reference=document.reference,
        file_name=document.file_name,
        title=document.file_name.rsplit(".", 1)[0],
        content_format="markdown",
        status=status,
        uploaded_at=NOW,
        chunk_count=chunk_count,
        error=error,
        revision=revision,
    )


class RecordingConnector:
    """KnowledgeConnector double that lists prepared documents and fetches sources."""

    def __init__(
        self,
        documents: Sequence[ConnectorDocument],
        sources: dict[str, SourceDocument] | None = None,
        *,
        fetch_errors: dict[str, BaseException] | None = None,
    ) -> None:
        self.documents = tuple(documents)
        self.sources = sources or {}
        self.fetch_errors = fetch_errors or {}
        self.fetched: list[ConnectorDocument] = []

    def list_documents(self) -> Sequence[ConnectorDocument]:
        return self.documents

    def fetch_document(self, document: ConnectorDocument) -> SourceDocument:
        self.fetched.append(document)
        error = self.fetch_errors.get(document.source_id)
        if error is not None:
            raise error
        return self.sources[document.source_id]


class RecordingIngest:
    """Records ingest requests and returns a fixed chunk count or error."""

    def __init__(
        self,
        *,
        chunk_count: int = 2,
        error: BaseException | None = None,
    ) -> None:
        self.chunk_count = chunk_count
        self.error = error
        self.calls: list[IngestRequest] = []

    def execute(self, request: IngestRequest) -> IngestResponse:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return IngestResponse(
            accepted_ids=[document.source_id for document in request.documents],
            chunk_count=self.chunk_count,
        )


class CountingFailCatalog(InMemoryDocumentCatalog):
    """Fails on a chosen upsert call number (1-based, including setup writes)."""

    def __init__(self, *, fail_on_call: int) -> None:
        super().__init__()
        self.fail_on_call = fail_on_call
        self.upserts = 0

    def upsert(self, document: CatalogDocument) -> None:
        self.upserts += 1
        if self.upserts == self.fail_on_call:
            raise RuntimeError("catalog upsert failed")
        super().upsert(document)


def _use_case(
    connector: RecordingConnector,
    catalog: InMemoryDocumentCatalog,
    *,
    ingest: RecordingIngest | IngestKnowledge | None = None,
    factory: object | None = None,
) -> SyncConnectorDocuments:
    ingest = ingest or RecordingIngest()
    return SyncConnectorDocuments(
        connector=connector,
        catalog=catalog,
        ingest_factory=factory or (lambda: ingest),
        now=FixedClock(NOW),
    )


def test_empty_folder_returns_empty_outcomes() -> None:
    connector = RecordingConnector(())
    ingest = RecordingIngest()
    response = _use_case(connector, InMemoryDocumentCatalog(), ingest=ingest).execute()
    assert response.outcomes == ()
    assert ingest.calls == []
    assert connector.fetched == []


def test_happy_path_fetches_ingests_and_persists_ready() -> None:
    listed = _listed()
    source = _source(listed)
    connector = RecordingConnector((listed,), {listed.source_id: source})
    catalog = InMemoryDocumentCatalog()
    ingest = RecordingIngest(chunk_count=3)
    response = _use_case(connector, catalog, ingest=ingest).execute()

    assert len(response.outcomes) == 1
    outcome = response.outcomes[0]
    assert outcome.source_id == "file-1"
    assert outcome.status is ConnectorSyncStatus.INGESTED
    assert outcome.chunk_count == 3
    assert outcome.error_type is None
    assert response.ingested_count == 1
    assert connector.fetched == [listed]
    assert len(ingest.calls) == 1
    assert list(ingest.calls[0].documents) == [source]
    stored = catalog.get(listed.reference)
    assert stored is not None
    assert stored.status is CatalogStatus.READY
    assert stored.revision == "1"
    assert stored.chunk_count == 3
    assert stored.file_name == "guide.md"


def test_ingest_pipeline_is_constructed_lazily_once() -> None:
    first = _listed("file-1")
    second = _listed("file-2", file_name="other.md")
    connector = RecordingConnector(
        (first, second),
        {first.source_id: _source(first), second.source_id: _source(second)},
    )
    ingest = RecordingIngest(chunk_count=1)
    calls = {"count": 0}

    def factory() -> RecordingIngest:
        calls["count"] += 1
        return ingest

    response = _use_case(
        connector, InMemoryDocumentCatalog(), ingest=ingest, factory=factory
    ).execute()

    assert response.ingested_count == 2
    assert calls["count"] == 1
    assert len(ingest.calls) == 2


def test_skip_only_run_does_not_construct_ingest() -> None:
    listed = _listed(revision="9")
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row(listed, revision="9"))
    connector = RecordingConnector((listed,), {})
    calls = {"count": 0}

    def factory() -> RecordingIngest:
        calls["count"] += 1
        raise AssertionError("ingest must not be built for a skip-only run")

    response = _use_case(
        connector, catalog, factory=factory
    ).execute()

    assert response.skipped_count == 1
    assert calls["count"] == 0
    assert connector.fetched == []


def test_matching_ready_revision_skips_fetch_and_embed() -> None:
    listed = _listed(revision="7")
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row(listed, revision="7", chunk_count=4))
    connector = RecordingConnector((listed,), {})
    ingest = RecordingIngest()
    response = _use_case(connector, catalog, ingest=ingest).execute()

    outcome = response.outcomes[0]
    assert outcome.status is ConnectorSyncStatus.SKIPPED
    assert outcome.chunk_count == 4
    assert connector.fetched == []
    assert ingest.calls == []
    assert catalog.get(listed.reference) == _row(listed, revision="7", chunk_count=4)


@pytest.mark.parametrize(
    "status",
    [CatalogStatus.FAILED, CatalogStatus.DEGRADED, CatalogStatus.PENDING],
)
def test_matching_non_ready_revision_is_retried(status: CatalogStatus) -> None:
    listed = _listed(revision="3")
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row(listed, status=status, revision="3", chunk_count=0))
    connector = RecordingConnector((listed,), {listed.source_id: _source(listed)})
    ingest = RecordingIngest(chunk_count=2)
    response = _use_case(connector, catalog, ingest=ingest).execute()

    assert response.outcomes[0].status is ConnectorSyncStatus.INGESTED
    assert connector.fetched == [listed]
    assert len(ingest.calls) == 1
    stored = catalog.get(listed.reference)
    assert stored is not None
    assert stored.status is CatalogStatus.READY
    assert stored.revision == "3"


def test_changed_revision_replaces_old_chunks() -> None:
    listed = _listed(revision="2")
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row(listed, revision="1", chunk_count=3))
    store = InMemoryVectorStore()
    ingest = IngestKnowledge(
        StubEmbeddingModel(),
        store,
        chunk_size=10,
        chunk_overlap=2,
    )
    connector = RecordingConnector((listed,), {listed.source_id: _source(listed)})
    response = SyncConnectorDocuments(
        connector=connector,
        catalog=catalog,
        ingest_factory=lambda: ingest,
        now=FixedClock(NOW),
    ).execute()

    assert response.outcomes[0].status is ConnectorSyncStatus.INGESTED
    stored = catalog.get(listed.reference)
    assert stored is not None
    assert stored.revision == "2"
    keys = [key for key in store.records if key[1] == "file-1"]
    assert keys
    indexes = sorted(key[2] for key in keys)
    assert indexes == list(range(len(indexes)))
    assert max(indexes) == stored.chunk_count - 1


def test_fewer_new_chunks_leave_no_stale_higher_index_chunks() -> None:
    listed = _listed(revision="2")
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row(listed, revision="1", chunk_count=3))
    store = InMemoryVectorStore()
    long_ingest = IngestKnowledge(
        StubEmbeddingModel(),
        store,
        chunk_size=10,
        chunk_overlap=2,
    )
    long_ingest.execute(
        IngestRequest(documents=(_source(listed, content=CONTENT),))
    )
    assert max(key[2] for key in store.records if key[1] == "file-1") > 0

    short = _source(listed, content="short")
    connector = RecordingConnector((listed,), {listed.source_id: short})
    response = SyncConnectorDocuments(
        connector=connector,
        catalog=catalog,
        ingest_factory=lambda: long_ingest,
        now=FixedClock(NOW),
    ).execute()

    assert response.outcomes[0].status is ConnectorSyncStatus.INGESTED
    keys = [key for key in store.records if key[1] == "file-1"]
    assert len(keys) == 1
    assert keys[0][2] == 0
    stored = catalog.get(listed.reference)
    assert stored is not None
    assert stored.chunk_count == 1
    assert stored.revision == "2"


def test_revision_change_is_not_hidden_by_unchanged_checksum_extra() -> None:
    listed = ConnectorDocument(
        reference=_reference(),
        file_name="renamed.md",
        revision="2",
        extra={"md5_checksum": "same"},
    )
    previous = ConnectorDocument(
        reference=_reference(),
        file_name="old.md",
        revision="1",
        extra={"md5_checksum": "same"},
    )
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row(previous, revision="1"))
    connector = RecordingConnector((listed,), {listed.source_id: _source(listed)})
    ingest = RecordingIngest(chunk_count=1)
    response = _use_case(connector, catalog, ingest=ingest).execute()

    assert response.outcomes[0].status is ConnectorSyncStatus.INGESTED
    stored = catalog.get(listed.reference)
    assert stored is not None
    assert stored.revision == "2"
    assert stored.file_name == "renamed.md"
    assert connector.fetched == [listed]


def test_fetch_failure_preserves_ready_row_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = _listed("file-1", revision="2")
    second = _listed("file-2", file_name="ok.md", revision="4")
    catalog = InMemoryDocumentCatalog()
    ready = _row(first, revision="1")
    catalog.upsert(ready)
    connector = RecordingConnector(
        (first, second),
        {second.source_id: _source(second)},
        fetch_errors={
            first.source_id: ConnectorError(f"could not read {SECRET}"),
        },
    )
    ingest = RecordingIngest(chunk_count=1)
    with caplog.at_level(logging.ERROR):
        response = _use_case(connector, catalog, ingest=ingest).execute()

    assert response.outcomes[0].status is ConnectorSyncStatus.FAILED
    assert response.outcomes[0].error_type == "ConnectorError"
    assert response.outcomes[0].chunk_count == 0
    assert SECRET not in (response.outcomes[0].error_type or "")
    assert response.outcomes[1].status is ConnectorSyncStatus.INGESTED
    assert catalog.get(first.reference) == ready
    assert catalog.get(second.reference) is not None
    assert catalog.get(second.reference).status is CatalogStatus.READY
    assert len(ingest.calls) == 1
    log_text = "\n".join(flatten_log_record(record) for record in caplog.records)
    assert SECRET not in log_text
    payloads = [
        record.getMessage()
        for record in operation_records(caplog.records, operation="connector_sync")
    ]
    assert payloads
    assert SECRET not in "".join(payloads)


def test_pre_mutation_ingest_failure_restores_previous_ready_row() -> None:
    listed = _listed(revision="2")
    catalog = InMemoryDocumentCatalog()
    previous = _row(listed, revision="1", chunk_count=5)
    catalog.upsert(previous)
    connector = RecordingConnector((listed,), {listed.source_id: _source(listed)})
    ingest = RecordingIngest(
        error=IngestFailure("embed failed", vector_mutation_started=False)
    )
    response = _use_case(connector, catalog, ingest=ingest).execute()

    assert response.outcomes[0].status is ConnectorSyncStatus.FAILED
    assert response.outcomes[0].error_type == "IngestFailure"
    assert catalog.get(listed.reference) == previous


def test_pre_mutation_ingest_failure_on_new_document_persists_failed() -> None:
    listed = _listed(revision="8")
    catalog = InMemoryDocumentCatalog()
    connector = RecordingConnector((listed,), {listed.source_id: _source(listed)})
    ingest = RecordingIngest(
        error=IngestFailure("embed failed", vector_mutation_started=False)
    )
    response = _use_case(connector, catalog, ingest=ingest).execute()

    stored = catalog.get(listed.reference)
    assert stored is not None
    assert stored.status is CatalogStatus.FAILED
    assert stored.revision == "8"
    assert response.outcomes[0].status is ConnectorSyncStatus.FAILED


def test_post_mutation_ingest_failure_persists_degraded_and_continues() -> None:
    first = _listed("file-1", revision="2")
    second = _listed("file-2", file_name="ok.md")
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row(first, revision="1"))
    connector = RecordingConnector(
        (first, second),
        {first.source_id: _source(first), second.source_id: _source(second)},
    )

    class _SelectiveIngest:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, request: IngestRequest) -> IngestResponse:
            self.calls += 1
            if self.calls == 1:
                raise IngestFailure("upsert failed", vector_mutation_started=True)
            return IngestResponse(
                accepted_ids=[document.source_id for document in request.documents],
                chunk_count=1,
            )

    ingest = _SelectiveIngest()
    response = _use_case(connector, catalog, ingest=ingest).execute()

    assert response.outcomes[0].status is ConnectorSyncStatus.FAILED
    first_row = catalog.get(first.reference)
    assert first_row is not None
    assert first_row.status is CatalogStatus.DEGRADED
    assert first_row.revision == "2"
    assert response.outcomes[1].status is ConnectorSyncStatus.INGESTED
    assert catalog.get(second.reference).status is CatalogStatus.READY


def test_pending_catalog_write_failure_aborts_the_run() -> None:
    listed = _listed()
    catalog = CountingFailCatalog(fail_on_call=1)
    connector = RecordingConnector((listed,), {listed.source_id: _source(listed)})
    ingest = RecordingIngest()
    with pytest.raises(RuntimeError, match="catalog upsert failed"):
        _use_case(connector, catalog, ingest=ingest).execute()
    assert ingest.calls == []
    assert catalog.get(listed.reference) is None


def test_recovery_catalog_write_failure_aborts_the_run() -> None:
    listed = _listed(revision="2")
    catalog = CountingFailCatalog(fail_on_call=3)
    catalog.upsert(_row(listed, revision="1"))
    connector = RecordingConnector((listed,), {listed.source_id: _source(listed)})
    ingest = RecordingIngest(
        error=IngestFailure("embed failed", vector_mutation_started=False)
    )
    with pytest.raises(RuntimeError, match="catalog upsert failed"):
        _use_case(connector, catalog, ingest=ingest).execute()


def test_ready_catalog_write_failure_aborts_the_run() -> None:
    listed = _listed()
    catalog = CountingFailCatalog(fail_on_call=2)
    connector = RecordingConnector((listed,), {listed.source_id: _source(listed)})
    ingest = RecordingIngest(chunk_count=1)
    with pytest.raises(RuntimeError, match="catalog upsert failed"):
        _use_case(connector, catalog, ingest=ingest).execute()
    pending = catalog.get(listed.reference)
    assert pending is not None
    assert pending.status is CatalogStatus.PENDING


def test_ingest_factory_failure_is_run_level_not_per_document() -> None:
    listed = _listed(revision="2")
    catalog = InMemoryDocumentCatalog()
    previous = _row(listed, revision="1", chunk_count=7)
    catalog.upsert(previous)
    connector = RecordingConnector((listed,), {listed.source_id: _source(listed)})

    def factory() -> RecordingIngest:
        raise RuntimeError("embedding credentials missing")

    with pytest.raises(RuntimeError, match="embedding credentials missing"):
        _use_case(connector, catalog, factory=factory).execute()
    assert catalog.get(listed.reference) == previous


def test_unknown_ingest_error_marks_degraded_and_aborts() -> None:
    listed = _listed(revision="2")
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row(listed, revision="1"))
    connector = RecordingConnector((listed,), {listed.source_id: _source(listed)})
    ingest = RecordingIngest(error=RuntimeError("store exploded"))
    with pytest.raises(RuntimeError, match="store exploded"):
        _use_case(connector, catalog, ingest=ingest).execute()
    stored = catalog.get(listed.reference)
    assert stored is not None
    assert stored.status is CatalogStatus.DEGRADED
    assert stored.revision == "2"
    assert stored.error == "RuntimeError"


def test_auth_failure_aborts_the_run_without_fetching_later_files() -> None:
    first = _listed("file-1")
    second = _listed("file-2", file_name="ok.md")
    connector = RecordingConnector(
        (first, second),
        {second.source_id: _source(second)},
        fetch_errors={first.source_id: ConnectorAuthError("credentials rejected")},
    )
    ingest = RecordingIngest()
    with pytest.raises(ConnectorAuthError):
        _use_case(connector, InMemoryDocumentCatalog(), ingest=ingest).execute()
    assert connector.fetched == [first]
    assert ingest.calls == []


def test_outcomes_follow_listing_order() -> None:
    first = _listed("b-file", file_name="b.md")
    second = _listed("a-file", file_name="a.md")
    connector = RecordingConnector(
        (first, second),
        {first.source_id: _source(first), second.source_id: _source(second)},
    )
    response = _use_case(connector, InMemoryDocumentCatalog()).execute()
    assert [outcome.source_id for outcome in response.outcomes] == [
        "b-file",
        "a-file",
    ]
