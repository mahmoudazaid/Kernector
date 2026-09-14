"""Composition wiring for GitHub connector sync."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from application.contracts import IngestRequest, IngestResponse
from application.errors import ConfigurationError
from composition import ConnectorSyncError, build_github_connector, sync_github
from composition import container as composition_container
from domain.errors import ConnectorError
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    ConnectorDocument,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.config import GitHubSettings, Settings, load_settings
from test.document_doubles import InMemoryDocumentCatalog
from test.doubles import InMemoryVectorStore

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


class RecordingConnector:
    def __init__(self, documents: tuple[ConnectorDocument, ...] = ()) -> None:
        self.documents = documents

    def list_documents(self) -> tuple[ConnectorDocument, ...]:
        return self.documents

    def fetch_document(self, document: ConnectorDocument) -> SourceDocument:
        return SourceDocument(
            SourceMetadata(
                document.reference,
                title=document.file_name,
                provider="github",
                content_format="markdown",
            ),
            "body",
        )


class RecordingIngest:
    def execute(self, request: IngestRequest) -> IngestResponse:
        return IngestResponse(
            accepted_ids=[document.source_id for document in request.documents],
            chunk_count=1,
        )


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CHROMA_PERSIST_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv(
        "GITHUB_OAUTH_TOKEN_PATH",
        str(tmp_path / "github-oauth-connection.json"),
    )
    monkeypatch.setenv(
        "GITHUB_OAUTH_STATE_PATH",
        str(tmp_path / "github-oauth-state.json"),
    )
    return load_settings()


def _listed(
    source_id: str = "repo:README.md",
    revision: str = "1",
    *,
    connector_id: str = "connector-cli",
) -> ConnectorDocument:
    return ConnectorDocument(
        reference=SourceReference(source_id, SourceType.GITHUB),
        file_name="README.md",
        revision=revision,
        extra={"connector_id": connector_id},
    )


def test_build_github_connector_maps_config_error(settings: Settings) -> None:
    settings = replace(settings, github=GitHubSettings(token=None, owner="octo", repo="repo"))

    with pytest.raises(ConfigurationError, match="configuration is invalid"):
        build_github_connector(settings)


def test_sync_github_reconciles_missing_github_rows(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    listed = _listed()
    stale = SourceReference("repo:old.md", SourceType.GITHUB)
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(
        CatalogDocument(
            reference=stale,
            file_name="old.md",
            title="old",
            content_format="markdown",
            status=CatalogStatus.READY,
            uploaded_at=NOW,
            chunk_count=1,
            error=None,
            revision="old",
            connector_id="connector-cli",
        )
    )
    store = InMemoryVectorStore()
    monkeypatch.setattr(
        composition_container,
        "build_ingest_knowledge",
        lambda _settings, *, vector_store=None: RecordingIngest(),
    )
    settings = replace(
        settings,
        github=replace(settings.github, connector_id="connector-cli"),
    )

    response = sync_github(
        settings,
        connector=RecordingConnector((listed,)),
        catalog=catalog,
        vector_store=store,
    )

    assert response.ingested_count == 1
    assert response.removed_count == 1
    assert catalog.get(stale) is None


def test_sync_github_requires_connector_id(settings: Settings) -> None:
    with pytest.raises(ConfigurationError, match="connector_id"):
        sync_github(
            settings,
            connector=RecordingConnector((_listed(),)),
            catalog=InMemoryDocumentCatalog(),
        )


def test_sync_github_wraps_listing_failure(settings: Settings) -> None:
    class FailingConnector(RecordingConnector):
        def list_documents(self) -> tuple[ConnectorDocument, ...]:
            raise ConnectorError("secret")

    settings = replace(
        settings,
        github=replace(settings.github, connector_id="connector-cli"),
    )
    with pytest.raises(ConnectorSyncError, match="GitHub connector sync failed"):
        sync_github(settings, connector=FailingConnector(), catalog=InMemoryDocumentCatalog())
