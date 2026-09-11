"""Composition wiring for Google Drive connector sync."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from application.contracts import IngestRequest, IngestResponse
from application.errors import ConfigurationError
from composition import (
    ConnectorSyncError,
    build_google_drive_connector,
    google_drive_status,
    load_runtime_settings,
    sync_google_drive,
)
from composition import container as composition_container
from domain.errors import ConnectorAuthError, ConnectorError, VectorStoreError
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    ConnectorDocument,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.catalog.errors import CatalogError
from infrastructure.config import GoogleDriveSettings, Settings, load_settings
from infrastructure.connectors.google_drive import GoogleDriveConfigError
from test.document_doubles import InMemoryDocumentCatalog

SECRET = "DRIVE-SECRET-TOKEN-LEAK"
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


class RecordingConnector:
    def __init__(
        self,
        documents: tuple[ConnectorDocument, ...] = (),
        *,
        list_error: BaseException | None = None,
        sources: dict[str, SourceDocument] | None = None,
        fetch_errors: dict[str, BaseException] | None = None,
    ) -> None:
        self.documents = documents
        self.list_error = list_error
        self.sources = sources or {}
        self.fetch_errors = fetch_errors or {}

    def list_documents(self) -> tuple[ConnectorDocument, ...]:
        if self.list_error is not None:
            raise self.list_error
        return self.documents

    def fetch_document(self, document: ConnectorDocument) -> SourceDocument:
        error = self.fetch_errors.get(document.source_id)
        if error is not None:
            raise error
        return self.sources[document.source_id]


class RecordingIngest:
    def __init__(self) -> None:
        self.calls: list[IngestRequest] = []

    def execute(self, request: IngestRequest) -> IngestResponse:
        self.calls.append(request)
        return IngestResponse(
            accepted_ids=[document.source_id for document in request.documents],
            chunk_count=1,
        )


class RecordingStore:
    def delete_source(self, reference: SourceReference) -> None:
        return None

    def upsert(self, embedded: object) -> None:
        return None

    def search(self, vector: object, limit: int, *, metadata_filters: object = None) -> tuple:
        return ()


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CHROMA_PERSIST_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv(
        "GOOGLE_OAUTH_TOKEN_PATH",
        str(tmp_path / "google-oauth-connection.json"),
    )
    monkeypatch.setenv(
        "GOOGLE_OAUTH_STATE_PATH",
        str(tmp_path / "google-oauth-state.json"),
    )
    monkeypatch.delenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_FOLDER_ID", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_PAGE_SIZE", raising=False)
    return load_settings()


def _listed(source_id: str = "file-1", revision: str = "1") -> ConnectorDocument:
    return ConnectorDocument(
        reference=SourceReference(source_id, SourceType.GOOGLE_DRIVE),
        file_name=f"{source_id}.md",
        revision=revision,
    )


def _source(document: ConnectorDocument) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            document.reference,
            title=document.file_name.rsplit(".", 1)[0],
            provider="google_drive",
            content_format="markdown",
        ),
        "body",
    )


def _ready_row(document: ConnectorDocument) -> CatalogDocument:
    return CatalogDocument(
        reference=document.reference,
        file_name=document.file_name,
        title=document.file_name.rsplit(".", 1)[0],
        content_format="markdown",
        status=CatalogStatus.READY,
        uploaded_at=NOW,
        chunk_count=2,
        error=None,
        revision=document.revision,
    )


def test_build_google_drive_connector_maps_config_error_without_path(
    settings: Settings,
) -> None:
    settings = replace(
        settings,
        google_drive=GoogleDriveSettings(
            service_account_file=Path("/secret/sa.json"),
            folder_id=None,
        ),
    )
    with pytest.raises(ConfigurationError, match="configuration is invalid") as raised:
        build_google_drive_connector(settings)
    assert "/secret/sa.json" not in str(raised.value)
    assert isinstance(raised.value.__cause__, GoogleDriveConfigError)


@pytest.mark.parametrize(
    "raw",
    [
        "bad id",
        "x' in parents or '' = '",
        "https://drive.google.com/drive/folders/abc123",
        "w" * 129,
    ],
)
def test_build_google_drive_connector_rejects_malformed_folder_id(
    settings: Settings, raw: str
) -> None:
    settings = replace(
        settings,
        google_drive=GoogleDriveSettings(
            service_account_file=Path("/secret/sa.json"),
            folder_id=raw,
        ),
    )
    with pytest.raises(ConfigurationError, match="GOOGLE_DRIVE_FOLDER_ID"):
        build_google_drive_connector(settings)


@pytest.mark.parametrize(
    "raw",
    [
        "bad id",
        "x' in parents or '' = '",
        "https://drive.google.com/drive/folders/abc123",
        "w" * 129,
    ],
)
def test_google_drive_status_configured_false_for_malformed_folder_id(
    settings: Settings, raw: str
) -> None:
    settings = replace(
        settings,
        google_drive=GoogleDriveSettings(
            service_account_file=Path("/secret/sa.json"),
            folder_id=raw,
        ),
    )
    assert google_drive_status(settings).configured is False


def test_google_drive_status_configured_true_for_valid_folder_id(
    settings: Settings,
) -> None:
    settings = replace(
        settings,
        google_drive=GoogleDriveSettings(
            service_account_file=Path("/secret/sa.json"),
            folder_id="1AbC_dEf-GhI",
        ),
    )
    status = google_drive_status(settings)
    assert status.configured is True
    # Pin OAuth store isolation: a real grant file must not make this True.
    assert status.connected is False


def test_build_google_drive_connector_maps_missing_client_extra(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    real_import = builtins.__import__

    def _import(
        name: str,
        globals: object = None,
        locals: object = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "infrastructure.connectors.google_drive":
            raise ImportError("No module named 'googleapiclient'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import)
    with pytest.raises(ConfigurationError, match="uv sync --extra google-drive") as raised:
        build_google_drive_connector(settings)
    assert "configuration is invalid" not in str(raised.value)
    assert isinstance(raised.value.__cause__, ImportError)


def test_sync_google_drive_wraps_listing_failure(settings: Settings) -> None:
    error = ConnectorAuthError(SECRET)
    with pytest.raises(ConnectorSyncError, match="sync failed") as raised:
        sync_google_drive(
            settings,
            connector=RecordingConnector(list_error=error),
            catalog=InMemoryDocumentCatalog(),
        )
    assert SECRET not in str(raised.value)
    assert raised.value.__cause__ is error


def test_sync_google_drive_wraps_catalog_failure(settings: Settings) -> None:
    listed = _listed()

    class FailingCatalog(InMemoryDocumentCatalog):
        def all(self) -> tuple[CatalogDocument, ...]:
            raise CatalogError(SECRET)

    with pytest.raises(ConnectorSyncError) as raised:
        sync_google_drive(
            settings,
            connector=RecordingConnector(
                (listed,), sources={listed.source_id: _source(listed)}
            ),
            catalog=FailingCatalog(),
        )
    assert SECRET not in str(raised.value)
    assert isinstance(raised.value.__cause__, CatalogError)


def test_sync_google_drive_wraps_store_failure(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    listed = _listed()

    def _store(_settings: Settings) -> RecordingStore:
        raise VectorStoreError(SECRET)

    monkeypatch.setattr(composition_container, "build_vector_store", _store)
    with pytest.raises(
        ConnectorSyncError, match="The Google Drive connector sync failed."
    ) as raised:
        sync_google_drive(
            settings,
            connector=RecordingConnector(
                (listed,), sources={listed.source_id: _source(listed)}
            ),
            catalog=InMemoryDocumentCatalog(),
        )
    assert SECRET not in str(raised.value)
    assert isinstance(raised.value.__cause__, VectorStoreError)


def test_skip_only_sync_does_not_build_ingest_or_store(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    listed = _listed(revision="2")
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_ready_row(listed))

    def _store(_settings: Settings) -> RecordingStore:
        raise AssertionError("vector store must not be built for skip-only sync")

    def _ingest(_settings: Settings, *, vector_store: object | None = None) -> RecordingIngest:
        raise AssertionError("ingest must not be built for skip-only sync")

    monkeypatch.setattr(composition_container, "build_vector_store", _store)
    monkeypatch.setattr(composition_container, "build_ingest_knowledge", _ingest)
    response = sync_google_drive(
        settings,
        connector=RecordingConnector((listed,)),
        catalog=catalog,
    )
    assert response.skipped_count == 1
    assert response.ingested_count == 0


def test_sync_reuses_one_ingest_and_one_store(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _listed("a")
    second = _listed("b")
    ingest = RecordingIngest()
    store = RecordingStore()
    store_calls = {"count": 0}
    ingest_calls = {"count": 0}

    def _store(_settings: Settings) -> RecordingStore:
        store_calls["count"] += 1
        return store

    def _ingest(_settings: Settings, *, vector_store: object | None = None) -> RecordingIngest:
        ingest_calls["count"] += 1
        assert vector_store is store
        return ingest

    monkeypatch.setattr(composition_container, "build_vector_store", _store)
    monkeypatch.setattr(composition_container, "build_ingest_knowledge", _ingest)
    response = sync_google_drive(
        settings,
        connector=RecordingConnector(
            (first, second),
            sources={first.source_id: _source(first), second.source_id: _source(second)},
        ),
        catalog=InMemoryDocumentCatalog(),
    )
    assert response.ingested_count == 2
    assert ingest_calls["count"] == 1
    assert store_calls["count"] == 1
    assert len(ingest.calls) == 2


def test_per_document_failures_stay_inside_the_response(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed = _listed("bad")
    ok = _listed("ok")
    monkeypatch.setattr(
        composition_container,
        "build_ingest_knowledge",
        lambda _settings, *, vector_store=None: RecordingIngest(),
    )
    monkeypatch.setattr(
        composition_container,
        "build_vector_store",
        lambda _settings: RecordingStore(),
    )
    response = sync_google_drive(
        settings,
        connector=RecordingConnector(
            (failed, ok),
            sources={ok.source_id: _source(ok)},
            fetch_errors={failed.source_id: ConnectorError(SECRET)},
        ),
        catalog=InMemoryDocumentCatalog(),
    )
    assert response.failed_count == 1
    assert response.ingested_count == 1
    assert response.outcomes[0].error_type == "ConnectorError"
    assert SECRET not in (response.outcomes[0].error_type or "")


def test_load_runtime_settings_still_works_without_drive_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_DRIVE_FOLDER_ID", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_PAGE_SIZE", raising=False)
    loaded = load_runtime_settings()
    assert loaded.google_drive.folder_id is None
