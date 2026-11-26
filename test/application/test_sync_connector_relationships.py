"""SyncConnectorDocuments relationship recording behaviour (#374)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from application.artifact.sync import SyncArtifactDescriptors
from application.contracts import ConnectorSyncStatus, IngestRequest, IngestResponse
from application.relationship.record import RecordExplicitRelationships
from application.relationship.transport import LINKS_FINGERPRINT_EXTRA_KEY
from application.sync_connector import SyncConnectorDocuments
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor, ArtifactRef
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    ConnectorDocument,
    ProcessingProfile,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from domain.relationship.models import (
    ORIGIN_PROVIDER_DECLARED,
    VERIFICATION_VERIFIED,
    EvidenceRef,
    ProviderLink,
    UnresolvedKey,
)
from infrastructure.artifact.sql_index import SqlArtifactIndex
from infrastructure.relationship.sql_store import SqlRelationshipStore
from test.document_doubles import FixedClock, InMemoryDocumentCatalog

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
PROFILE = ProcessingProfile(
    chunker_version="1",
    chunk_size=10,
    chunk_overlap=2,
    embedding_model="test-embedding",
)


class _FixedExtractor:
    def __init__(self, links: tuple[ProviderLink, ...] = ()) -> None:
        self.links = links

    def extract(self, document, raw):  # noqa: ANN001
        del document, raw
        return self.links


class _RecordingIngest:
    def execute(self, request: IngestRequest) -> IngestResponse:
        return IngestResponse(
            accepted_ids=[document.source_id for document in request.documents],
            chunk_count=1,
        )


class _Connector:
    def __init__(
        self,
        listed: tuple[ConnectorDocument, ...],
        sources: dict[str, SourceDocument],
    ) -> None:
        self._listed = listed
        self._sources = sources
        self.fetched: list[ConnectorDocument] = []

    def list_documents(self) -> tuple[ConnectorDocument, ...]:
        return self._listed

    def fetch_document(self, document: ConnectorDocument) -> SourceDocument:
        self.fetched.append(document)
        return self._sources[document.source_id]


class _ExplodingStore(SqlRelationshipStore):
    def list_unresolved_for_key(self, key: str, *, part_key: str | None = None):
        raise RuntimeError("lookup failed")


def _jira_ref(source_id: str) -> SourceReference:
    return SourceReference(source_id, SourceType.JIRA)


def _listed(
    source_id: str,
    *,
    revision: str = "2026-10-01T12:00:00.000+0000",
    fingerprint: str | None = None,
) -> ConnectorDocument:
    extra: dict[str, str] = {}
    if fingerprint is not None:
        extra[LINKS_FINGERPRINT_EXTRA_KEY] = fingerprint
    return ConnectorDocument(
        reference=_jira_ref(source_id),
        file_name=f"{source_id.rsplit(':', 1)[-1]}.md",
        revision=revision,
        extra=extra,
    )


def _source(
    document: ConnectorDocument,
    *,
    fingerprint: str = "fp-1",
) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            document.reference,
            title=document.file_name,
            provider="jira",
            content_format="markdown",
            extra={
                "file_name": document.file_name,
                LINKS_FINGERPRINT_EXTRA_KEY: fingerprint,
            },
        ),
        f"# {document.file_name}",
    )


def _row(document: ConnectorDocument, *, chunk_count: int = 1) -> CatalogDocument:
    return CatalogDocument(
        reference=document.reference,
        file_name=document.file_name,
        title=document.file_name,
        content_format="markdown",
        status=CatalogStatus.READY,
        created_at=NOW,
        updated_at=NOW,
        chunk_count=chunk_count,
        error=None,
        revision=document.revision,
        connector_id="jira-1",
        content_fingerprint="content-fp",
        metadata_fingerprint="meta-fp",
        processing_fingerprint=PROFILE.fingerprint,
    )


def _descriptor(source_id: str, key: str) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        reference=_jira_ref(source_id),
        revision="r1",
        kind=ArtifactKind.STORY,
        external_keys=(key,),
        title=key,
    )


class _Describe:
    def describe(self, source: SourceDocument) -> ArtifactDescriptor:
        key = source.reference.source_id.rsplit(":", 1)[-1]
        return _descriptor(source.reference.source_id, key)


def _sync(
    path: Path,
    connector: _Connector,
    catalog: InMemoryDocumentCatalog,
    *,
    store: SqlRelationshipStore | None = None,
    projects: dict[str, tuple[str, ...]] | None = None,
    extractor: _FixedExtractor | None = None,
    recorder: RecordExplicitRelationships | None = None,
) -> tuple[
    SyncConnectorDocuments,
    SqlRelationshipStore,
    SqlArtifactIndex,
    SyncArtifactDescriptors,
]:
    store = store or SqlRelationshipStore(path, "ws-a")
    index = SqlArtifactIndex(path, "ws-a")
    project_map = projects if projects is not None else {}
    if recorder is None:
        recorder = RecordExplicitRelationships(
            store,
            index,
            project_ids_for=lambda ref: project_map.get(
                ref.source_id, ("prj_orders",)
            ),
            extractors={"jira": extractor or _FixedExtractor()},
            raw_from_document=lambda _source: {
                "v": 1,
                "issue_key": "x",
                "links": [],
            },
            mapping_fingerprint="map-1",
        )
    artifact_sync = SyncArtifactDescriptors(
        extractor=_Describe(),
        index=index,
        relationships=recorder,
    )
    use_case = SyncConnectorDocuments(
        connector=connector,
        catalog=catalog,
        ingest_factory=lambda: _RecordingIngest(),
        now=FixedClock(NOW),
        processing_profile=PROFILE,
        artifact_sync=artifact_sync,
    )
    return use_case, store, index, artifact_sync


def test_lookup_error_on_skipped_issue_does_not_abort_sync(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    skipped = _listed("inst/PROJ:PROJ-1", fingerprint="fp-1")
    new_a = _listed("inst/PROJ:PROJ-2", fingerprint="fp-2")
    new_b = _listed("inst/PROJ:PROJ-3", fingerprint="fp-3")
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row(skipped))
    sources = {
        skipped.source_id: _source(skipped),
        new_a.source_id: _source(new_a, fingerprint="fp-2"),
        new_b.source_id: _source(new_b, fingerprint="fp-3"),
    }
    connector = _Connector((skipped, new_a, new_b), sources)
    use_case, _store, index, _sync_hook = _sync(
        path,
        connector,
        catalog,
        store=_ExplodingStore(path, "ws-a"),
    )
    index.upsert(_descriptor(skipped.source_id, "PROJ-1"))

    response = use_case.execute()

    assert [item.status for item in response.outcomes] == [
        ConnectorSyncStatus.SKIPPED,
        ConnectorSyncStatus.INGESTED,
        ConnectorSyncStatus.INGESTED,
    ]
    assert response.ingested_count == 2


def test_link_fingerprint_change_with_same_revision_retries(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite"
    listed = _listed("inst/PROJ:PROJ-140", fingerprint="fp-new")
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row(listed))
    source = _source(listed, fingerprint="fp-new")
    connector = _Connector((listed,), {listed.source_id: source})
    links = (
        ProviderLink(
            relation_type="tests",
            subject_key="PROJ-140",
            object_key="PROJ-123",
            locator="field=issuelinks;type=Tests;dir=out;key=PROJ-123",
        ),
    )
    use_case, store, index, _hook = _sync(
        path, connector, catalog, extractor=_FixedExtractor(links)
    )
    index.upsert(_descriptor(listed.source_id, "PROJ-140"))
    index.upsert(_descriptor("inst/PROJ:PROJ-123", "PROJ-123"))
    store.set_record_watermark(
        listed.reference,
        "v2\nfp-old\n2026-10-01T12:00:00.000+0000\nprj_orders\nmap-1",
    )

    response = use_case.execute()

    assert response.outcomes[0].status is ConnectorSyncStatus.SKIPPED
    assert connector.fetched == [listed]
    listed_edges = store.list_for_artifact(
        "prj_orders", ArtifactRef(_jira_ref("inst/PROJ:PROJ-123"))
    )
    assert len(listed_edges) == 1


def test_arrival_failure_retries_on_next_sync(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    target = _listed("inst/PROJ:PROJ-9", fingerprint="fp-1")
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row(target))
    source = _source(target)
    connector = _Connector((target,), {target.source_id: source})
    store = SqlRelationshipStore(path, "ws-a")
    index = SqlArtifactIndex(path, "ws-a")
    index.upsert(_descriptor(target.source_id, "PROJ-9"))
    store.upsert_from_evidence(
        project_id="prj_orders",
        subject=ArtifactRef(_jira_ref("inst/PROJ:PROJ-1")),
        relation_type="relates_to",
        object=UnresolvedKey("PROJ-9"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=EvidenceRef(
            source=_jira_ref("inst/PROJ:PROJ-1"),
            revision="r1",
            locator="field=issuelinks;type=Relates;dir=out;key=PROJ-9",
            extractor_id="jira_explicit_links",
        ),
        seen_at="2026-10-01T12:00:00Z",
    )
    store.set_record_watermark(
        target.reference,
        "v2\nfp-1\n2026-10-01T12:00:00.000+0000\nprj_orders\nmap-1",
    )

    class _FailOnceRecorder(RecordExplicitRelationships):
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002
            super().__init__(*args, **kwargs)
            self.calls = 0

        def resolve_arriving(self, source_doc: SourceDocument) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("arrival failed")
            super().resolve_arriving(source_doc)

    recorder = _FailOnceRecorder(
        store,
        index,
        project_ids_for=lambda _ref: ("prj_orders",),
        extractors={"jira": _FixedExtractor()},
        raw_from_document=lambda _source: {"v": 1, "issue_key": "x", "links": []},
        mapping_fingerprint="map-1",
    )
    use_case, _store, _index, _hook = _sync(
        path, connector, catalog, store=store, recorder=recorder
    )

    first = use_case.execute()
    assert first.outcomes[0].status is ConnectorSyncStatus.SKIPPED
    assert len(store.list_unresolved_for_key("PROJ-9")) == 1

    second = use_case.execute()
    assert second.outcomes[0].status is ConnectorSyncStatus.SKIPPED
    resolved = store.list_for_artifact(
        "prj_orders", ArtifactRef(_jira_ref("inst/PROJ:PROJ-9"))
    )
    assert len(resolved) == 1
    assert isinstance(resolved[0].object, ArtifactRef)


def test_arrival_runs_for_target_without_project(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    target = _listed("inst/PROJ:PROJ-9", fingerprint="fp-1")
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row(target))
    source = _source(target)
    connector = _Connector((target,), {target.source_id: source})
    projects = {target.source_id: ()}
    use_case, store, index, _hook = _sync(
        path, connector, catalog, projects=projects
    )
    index.upsert(_descriptor(target.source_id, "PROJ-9"))
    store.upsert_from_evidence(
        project_id="prj_orders",
        subject=ArtifactRef(_jira_ref("inst/PROJ:PROJ-1")),
        relation_type="relates_to",
        object=UnresolvedKey("PROJ-9"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=EvidenceRef(
            source=_jira_ref("inst/PROJ:PROJ-1"),
            revision="r1",
            locator="field=issuelinks;type=Relates;dir=out;key=PROJ-9",
            extractor_id="jira_explicit_links",
        ),
        seen_at="2026-10-01T12:00:00Z",
    )

    response = use_case.execute()

    assert response.outcomes[0].status is ConnectorSyncStatus.SKIPPED
    assert store.get_record_watermark(target.reference) is None
    resolved = store.list_for_artifact(
        "prj_orders", ArtifactRef(_jira_ref("inst/PROJ:PROJ-9"))
    )
    assert len(resolved) == 1
    assert isinstance(resolved[0].object, ArtifactRef)


def test_removed_target_clears_watermark_and_rerecords_on_return(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite"
    listed = _listed("inst/PROJ:PROJ-140", fingerprint="fp-1")
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row(listed))
    source = _source(listed)
    connector = _Connector((listed,), {listed.source_id: source})
    links = (
        ProviderLink(
            relation_type="tests",
            subject_key="PROJ-140",
            object_key="PROJ-123",
            locator="field=issuelinks;type=Tests;dir=out;key=PROJ-123",
        ),
    )
    use_case, store, index, artifact_sync = _sync(
        path, connector, catalog, extractor=_FixedExtractor(links)
    )
    index.upsert(_descriptor(listed.source_id, "PROJ-140"))
    index.upsert(_descriptor("inst/PROJ:PROJ-123", "PROJ-123"))
    use_case.execute()
    assert store.get_record_watermark(listed.reference) is not None

    artifact_sync.on_removed(listed.reference)
    assert store.get_record_watermark(listed.reference) is None

    returned = _Connector((listed,), {listed.source_id: source})
    use_case_return, store, _index, _hook = _sync(
        path, returned, catalog, store=store, extractor=_FixedExtractor(links)
    )
    response = use_case_return.execute()
    assert response.outcomes[0].status is ConnectorSyncStatus.SKIPPED
    assert store.get_record_watermark(listed.reference) is not None
