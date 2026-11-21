"""Per-identity sync, purge, and partial failure (#388 Slice 2)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from application.contracts import (
    IngestRequest,
    IngestResponse,
)
from composition import put_github_selection, sync_github_oauth
from composition import container as composition_container
from composition.github import sync as github_sync
from composition.github.models import GitHubRepoTarget
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
from infrastructure.config import GitHubOAuthSettings, GitHubSettings, load_settings
from infrastructure.connectors.github.oauth import (
    GitHubOAuthConnection,
    GitHubOAuthConnectionStore,
)
from test.document_doubles import InMemoryDocumentCatalog
from test.doubles import InMemoryVectorStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CHROMA_PERSIST_PATH", str(tmp_path / "chroma"))
    loaded = load_settings()
    return replace(
        loaded,
        github=GitHubSettings(
            extensions=(".md", ".py", ".txt"),
            max_repositories=16,
        ),
        github_oauth=GitHubOAuthSettings(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="http://127.0.0.1:8000/api/v1/connectors/github/oauth/callback",
            frontend_redirect="http://localhost:3000/documents",
            token_path=tmp_path / "github-oauth-connection.json",
            state_path=tmp_path / "github-oauth-state.json",
            state_ttl_seconds=600,
        ),
    )


def _grant(tokens: GitHubOAuthConnectionStore, **overrides) -> None:
    base = dict(
        access_token="gho-access-secret",
        refresh_token=None,
        account_login="ada",
        owner=None,
        repo=None,
        project_owner=None,
        project_number=None,
        last_synced_at=None,
        last_sync_new=None,
        last_sync_updated=None,
        last_sync_unchanged=None,
        last_sync_removed=None,
        last_sync_failed=None,
        reauthorization_required=False,
        connector_id="connector-a",
    )
    base.update(overrides)
    tokens.mutate(lambda _c: GitHubOAuthConnection(**base))


class _AcceptClient:
    def get_repository(self, owner: str, repo: str):
        return {"full_name": f"{owner}/{repo}"}

    def resolve_project_v2_id(self, owner_login: str, number: int) -> str:
        return f"PVT_{owner_login}_{number}"


def _row(source_id: str, *, connector_id: str = "connector-a") -> CatalogDocument:
    return CatalogDocument(
        reference=SourceReference(source_id, SourceType.GITHUB),
        file_name=source_id.split(":")[-1],
        title=source_id,
        content_format="markdown",
        status=CatalogStatus.READY,
        created_at=NOW,
        updated_at=NOW,
        chunk_count=1,
        error=None,
        revision="1",
        connector_id=connector_id,
    )


class _RepoConnector:
    def __init__(self, docs: tuple[ConnectorDocument, ...]) -> None:
        self._docs = docs

    def list_documents(self) -> tuple[ConnectorDocument, ...]:
        return self._docs

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


class _Ingest:
    def execute(self, request: IngestRequest) -> IngestResponse:
        return IngestResponse(
            accepted_ids=[document.source_id for document in request.documents],
            chunk_count=1,
        )


def _doc(source_id: str, *, connector_id: str = "connector-a") -> ConnectorDocument:
    owner, rest = source_id.split("/", 1)
    repo, path = rest.split(":", 1)
    return ConnectorDocument(
        reference=SourceReference(source_id, SourceType.GITHUB),
        file_name=path,
        revision="1",
        extra={
            "connector_id": connector_id,
            "owner": owner,
            "repo": repo,
            "path": path,
            "github_kind": "repo",
        },
    )


def test_two_identities_sync_with_correct_owner_repo(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    _grant(tokens)
    put_github_selection(
        settings,
        repositories=(
            GitHubRepoTarget(owner="acme", repo="web"),
            GitHubRepoTarget(owner="acme", repo="orders"),
        ),
        connection_store=tokens,
        client_factory=lambda _t: _AcceptClient(),
    )
    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    monkeypatch.setattr(
        composition_container,
        "build_ingest_knowledge",
        lambda _settings, *, vector_store=None: _Ingest(),
    )

    def build(_settings, *, token: str):
        owner = _settings.github.owner
        repo = _settings.github.repo
        return _RepoConnector(
            (_doc(f"{owner}/{repo}:README.md"),)
        )

    monkeypatch.setattr(github_sync, "build_github_oauth_connector", build)

    result = sync_github_oauth(
        settings,
        catalog=catalog,
        vector_store=store,
        connection_store=tokens,
    )

    ids = {row.reference.source_id for row in catalog.all()}
    assert ids == {"acme/web:README.md", "acme/orders:README.md"}
    assert result.ingested_count == 2

    again = sync_github_oauth(
        settings,
        catalog=catalog,
        vector_store=store,
        connection_store=tokens,
    )
    assert again.skipped_count == 2
    assert again.ingested_count == 0


def test_remove_one_identity_purges_only_its_docs(settings) -> None:
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    _grant(tokens)
    put_github_selection(
        settings,
        repositories=(
            GitHubRepoTarget(owner="acme", repo="web"),
            GitHubRepoTarget(owner="acme", repo="orders"),
        ),
        connection_store=tokens,
        client_factory=lambda _t: _AcceptClient(),
    )
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("acme/web:README.md"))
    catalog.upsert(_row("acme/orders:README.md"))
    catalog.upsert(_row("issue:ISSUE_1"))
    store = InMemoryVectorStore()

    put_github_selection(
        settings,
        repositories=(GitHubRepoTarget(owner="acme", repo="web"),),
        connection_store=tokens,
        client_factory=lambda _t: _AcceptClient(),
        catalog=catalog,
        vector_store=store,
    )

    ids = {row.reference.source_id for row in catalog.all()}
    assert ids == {"acme/web:README.md", "issue:ISSUE_1"}


def test_config_change_reconciles_paths_for_one_identity(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    _grant(tokens)
    put_github_selection(
        settings,
        repositories=(
            GitHubRepoTarget(
                owner="acme",
                repo="web",
                extensions=(".md", ".tsx"),
            ),
            GitHubRepoTarget(owner="acme", repo="orders"),
        ),
        connection_store=tokens,
        client_factory=lambda _t: _AcceptClient(),
    )
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("acme/web:App.tsx"))
    catalog.upsert(_row("acme/web:README.md"))
    catalog.upsert(_row("acme/orders:README.md"))
    store = InMemoryVectorStore()
    monkeypatch.setattr(
        composition_container,
        "build_ingest_knowledge",
        lambda _settings, *, vector_store=None: _Ingest(),
    )

    put_github_selection(
        settings,
        repositories=(
            GitHubRepoTarget(
                owner="acme",
                repo="web",
                extensions=(".md",),
            ),
            GitHubRepoTarget(owner="acme", repo="orders"),
        ),
        connection_store=tokens,
        client_factory=lambda _t: _AcceptClient(),
        catalog=catalog,
        vector_store=store,
    )
    # Config-only put must not purge yet.
    assert catalog.get(SourceReference("acme/web:App.tsx", SourceType.GITHUB))

    def build(_settings, *, token: str):
        owner = _settings.github.owner
        repo = _settings.github.repo
        if owner == "acme" and repo == "web":
            return _RepoConnector((_doc("acme/web:README.md"),))
        return _RepoConnector((_doc("acme/orders:README.md"),))

    monkeypatch.setattr(github_sync, "build_github_oauth_connector", build)

    sync_github_oauth(
        settings,
        catalog=catalog,
        vector_store=store,
        connection_store=tokens,
    )

    ids = {row.reference.source_id for row in catalog.all()}
    assert ids == {"acme/web:README.md", "acme/orders:README.md"}


def test_partial_failure_keeps_successful_peer_docs(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    _grant(tokens)
    put_github_selection(
        settings,
        repositories=(
            GitHubRepoTarget(owner="acme", repo="web"),
            GitHubRepoTarget(owner="acme", repo="orders"),
        ),
        connection_store=tokens,
        client_factory=lambda _t: _AcceptClient(),
    )
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_row("acme/orders:README.md"))
    store = InMemoryVectorStore()
    monkeypatch.setattr(
        composition_container,
        "build_ingest_knowledge",
        lambda _settings, *, vector_store=None: _Ingest(),
    )

    def build(_settings, *, token: str):
        if _settings.github.repo == "orders":
            raise ConnectorError("orders listing failed")
        return _RepoConnector((_doc("acme/web:README.md"),))

    monkeypatch.setattr(github_sync, "build_github_oauth_connector", build)

    result = sync_github_oauth(
        settings,
        catalog=catalog,
        vector_store=store,
        connection_store=tokens,
    )

    ids = {row.reference.source_id for row in catalog.all()}
    assert "acme/web:README.md" in ids
    assert "acme/orders:README.md" in ids
    assert result.ingested_count == 1

    # Retry after orders recovers.
    def build_ok(_settings, *, token: str):
        owner = _settings.github.owner
        repo = _settings.github.repo
        return _RepoConnector((_doc(f"{owner}/{repo}:README.md"),))

    monkeypatch.setattr(github_sync, "build_github_oauth_connector", build_ok)
    retry = sync_github_oauth(
        settings,
        catalog=catalog,
        vector_store=store,
        connection_store=tokens,
    )
    assert catalog.get(SourceReference("acme/web:README.md", SourceType.GITHUB))
    assert catalog.get(SourceReference("acme/orders:README.md", SourceType.GITHUB))
    assert retry.skipped_count >= 1
