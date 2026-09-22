"""User OAuth composition for GitHub — mocked gateway; no live credentials."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from application.contracts import (
    ConnectorSyncOutcome,
    ConnectorSyncResponse,
    ConnectorSyncStatus,
)
from application.errors import GitHubNotConnectedError, GitHubReauthorizationRequiredError
from composition import (
    complete_github_oauth,
    disconnect_github_oauth,
    github_status,
    start_github_oauth,
    sync_github_oauth,
)
from composition import container as composition_container
from domain.errors import ConnectorAuthError
from infrastructure.config import GitHubOAuthSettings, GitHubSettings, load_settings
from infrastructure.connectors.github.oauth import (
    GitHubOAuthConnection,
    GitHubOAuthConnectionStore,
    GitHubOAuthGrant,
    GitHubOAuthStateStore,
)
from test.document_doubles import InMemoryDocumentCatalog


class FakeGateway:
    def __init__(self) -> None:
        self.revoked: list[str] = []
        self.refresh_calls: list[str] = []

    def exchange_code(self, code: str) -> GitHubOAuthGrant:
        assert code == "code"
        return GitHubOAuthGrant(
            access_token="gho-access-secret",
            refresh_token="ghr-refresh-secret",
        )

    def refresh(self, refresh_token: str) -> GitHubOAuthGrant:
        self.refresh_calls.append(refresh_token)
        return GitHubOAuthGrant(
            access_token="gho-refreshed-secret",
            refresh_token=refresh_token,
        )

    def fetch_account_login(self, _access_token: str) -> str | None:
        return "ada"

    def revoke(self, token: str) -> None:
        self.revoked.append(token)


@pytest.fixture
def settings(tmp_path: Path):
    loaded = load_settings()
    return replace(
        loaded,
        github=GitHubSettings(owner="octo", repo="repo"),
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


def test_start_without_oauth_client_returns_hub_redirect(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GITHUB_OAUTH_REDIRECT_URI", raising=False)

    url = start_github_oauth(load_settings())

    assert url.endswith("github=unconfigured")


def test_callback_persists_connection(settings) -> None:
    states = GitHubOAuthStateStore(settings.github_oauth.state_path, ttl_seconds=600)
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    state = states.issue()

    url = complete_github_oauth(
        settings,
        state=state,
        code="code",
        error=None,
        state_store=states,
        connection_store=tokens,
        gateway=FakeGateway(),
    )

    assert url == "http://localhost:3000/documents?github=connected"
    stored = tokens.load()
    assert stored is not None
    assert stored.account_login == "ada"
    assert stored.owner == "octo"
    assert stored.repo == "repo"
    assert "gho-access-secret" not in url


def test_disconnect_revokes_and_clears(settings) -> None:
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.save(
        GitHubOAuthConnection(
            access_token="gho-access-secret",
            refresh_token=None,
            account_login="ada",
            owner="octo",
            repo="repo",
            project_owner=None,
            project_number=None,
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_removed=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )
    gateway = FakeGateway()

    disconnect_github_oauth(settings, connection_store=tokens, gateway=gateway)

    assert gateway.revoked == ["gho-access-secret"]
    assert tokens.load() is None
    with pytest.raises(GitHubNotConnectedError):
        disconnect_github_oauth(settings, connection_store=tokens, gateway=gateway)


def test_disconnect_github_oauth_purges_repo_and_issue_docs(settings) -> None:
    from composition import disconnect_github_oauth
    from test.document_doubles import InMemoryDocumentCatalog
    from test.doubles import InMemoryVectorStore

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.mutate(
        lambda _current: GitHubOAuthConnection(
            access_token="gho-access-secret",
            refresh_token=None,
            account_login="ada",
            owner="acme",
            repo="docs",
            project_owner="acme",
            project_number=16,
            connector_id="connector-a",
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_removed=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_github_catalog_row("acme/docs:README.md"))
    catalog.upsert(_github_catalog_row("issue:ISSUE_1"))
    catalog.upsert(
        _github_catalog_row("other/repo:kept.md", connector_id="connector-b")
    )
    store = InMemoryVectorStore()
    gateway = FakeGateway()

    disconnect_github_oauth(
        settings,
        connection_store=tokens,
        gateway=gateway,
        catalog=catalog,
        vector_store=store,
    )

    assert tokens.load() is None
    ids = {row.reference.source_id for row in catalog.all()}
    assert ids == {"other/repo:kept.md"}


def test_oauth_sync_persists_counts(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.save(
        GitHubOAuthConnection(
            access_token="gho-access-secret",
            refresh_token=None,
            account_login="ada",
            owner="octo",
            repo="repo",
            project_owner=None,
            project_number=None,
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_removed=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )
    monkeypatch.setattr(
        composition_container,
        "build_github_oauth_connector",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        composition_container,
        "sync_github",
        lambda *_args, **_kwargs: ConnectorSyncResponse(
            outcomes=(
                ConnectorSyncOutcome("new", ConnectorSyncStatus.INGESTED, 1),
                ConnectorSyncOutcome("old", ConnectorSyncStatus.REMOVED, 0),
            )
        ),
    )

    result = sync_github_oauth(
        settings,
        catalog=InMemoryDocumentCatalog(),
        vector_store=object(),  # type: ignore[arg-type]
        connection_store=tokens,
    )

    stored = tokens.load()
    assert stored is not None
    assert stored.last_sync_new == 1
    assert stored.last_sync_removed == 1
    assert stored.last_synced_at is not None
    assert result.removed_count == 1
    assert github_status(settings).connected is True


def test_oauth_sync_marks_reauth_on_auth_error(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.save(
        GitHubOAuthConnection(
            access_token="gho-access-secret",
            refresh_token=None,
            account_login="ada",
            owner="octo",
            repo="repo",
            project_owner=None,
            project_number=None,
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_removed=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )
    monkeypatch.setattr(
        composition_container,
        "build_github_oauth_connector",
        lambda *_args, **_kwargs: object(),
    )

    def fail_sync(*_args, **_kwargs):
        raise composition_container.ConnectorSyncError(
            "The GitHub connector sync failed."
        ) from ConnectorAuthError("secret")

    monkeypatch.setattr(composition_container, "sync_github", fail_sync)

    with pytest.raises(GitHubReauthorizationRequiredError):
        sync_github_oauth(
            settings,
            catalog=InMemoryDocumentCatalog(),
            vector_store=object(),  # type: ignore[arg-type]
            connection_store=tokens,
        )

    assert tokens.load().reauthorization_required is True


def test_oauth_sync_refreshes_token_then_retries(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.save(
        GitHubOAuthConnection(
            access_token="gho-access-secret",
            refresh_token="ghr-refresh-secret",
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
        )
    )
    seen_tokens: list[str] = []
    calls = {"n": 0}

    def flaky_sync(sync_settings, **_kwargs):
        calls["n"] += 1
        seen_tokens.append(sync_settings.github.token or "")
        if calls["n"] == 1:
            raise composition_container.ConnectorSyncError(
                "The GitHub connector sync failed."
            ) from ConnectorAuthError("expired")
        return ConnectorSyncResponse(
            outcomes=(ConnectorSyncOutcome("ok", ConnectorSyncStatus.INGESTED, 1),)
        )

    monkeypatch.setattr(
        composition_container,
        "build_github_oauth_connector",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(composition_container, "sync_github", flaky_sync)
    gateway = FakeGateway()

    result = sync_github_oauth(
        settings,
        catalog=InMemoryDocumentCatalog(),
        vector_store=object(),  # type: ignore[arg-type]
        connection_store=tokens,
        oauth_gateway=gateway,
    )

    assert result.ingested_count == 1
    assert gateway.refresh_calls == ["ghr-refresh-secret"]
    assert seen_tokens == ["gho-access-secret", "gho-refreshed-secret"]
    stored = tokens.load()
    assert stored is not None
    assert stored.access_token == "gho-refreshed-secret"
    assert stored.owner == "octo"
    assert stored.repo == "repo"
    assert stored.reauthorization_required is False


def test_oauth_sync_refreshes_when_connector_build_raises_auth(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Constructor auth errors must wrap as sync errors so refresh runs."""
    settings = replace(
        settings,
        github=replace(
            settings.github,
            project_owner="ada",
            project_number=1,
        ),
    )
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.save(
        GitHubOAuthConnection(
            access_token="gho-access-secret",
            refresh_token="ghr-refresh-secret",
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
        )
    )
    build_tokens: list[str] = []

    def flaky_build(sync_settings, *, token: str):
        build_tokens.append(token)
        if token == "gho-access-secret":
            raise ConnectorAuthError("expired")
        return object()

    monkeypatch.setattr(
        composition_container,
        "build_github_oauth_connector",
        flaky_build,
    )
    monkeypatch.setattr(
        composition_container,
        "sync_github",
        lambda *_args, **_kwargs: ConnectorSyncResponse(
            outcomes=(ConnectorSyncOutcome("ok", ConnectorSyncStatus.INGESTED, 1),)
        ),
    )
    gateway = FakeGateway()

    result = sync_github_oauth(
        settings,
        catalog=InMemoryDocumentCatalog(),
        vector_store=object(),  # type: ignore[arg-type]
        connection_store=tokens,
        oauth_gateway=gateway,
    )

    assert result.ingested_count == 1
    assert gateway.refresh_calls == ["ghr-refresh-secret"]
    assert build_tokens == ["gho-access-secret", "gho-refreshed-secret"]
    stored = tokens.load()
    assert stored is not None
    assert stored.access_token == "gho-refreshed-secret"
    assert stored.reauthorization_required is False


def test_start_oauth_without_env_repo_still_issues_github_url(settings) -> None:
    from dataclasses import replace as dc_replace

    bare = dc_replace(settings, github=GitHubSettings())
    url = start_github_oauth(bare)
    assert "github.com/login/oauth/authorize" in url


def test_sync_oauth_without_selection_raises(settings, tmp_path: Path) -> None:
    from application.errors import GitHubSelectionRequiredError

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.mutate(
        lambda _current: GitHubOAuthConnection(
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
        )
    )
    bare = replace(settings, github=GitHubSettings())
    with pytest.raises(GitHubSelectionRequiredError):
        sync_github_oauth(
            bare,
            catalog=InMemoryDocumentCatalog(),
            vector_store=object(),  # type: ignore[arg-type]
            connection_store=tokens,
            oauth_gateway=FakeGateway(),
        )


def test_put_github_selection_persists_validated_repo(settings) -> None:
    from composition import put_github_selection

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.mutate(
        lambda _current: GitHubOAuthConnection(
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
        )
    )

    class FakeClient:
        def get_repository(self, owner: str, repo: str):
            assert owner == "acme"
            assert repo == "docs"
            return {"full_name": "acme/docs"}

        def resolve_project_v2_id(self, owner_login: str, number: int) -> str:
            assert owner_login == "acme"
            assert number == 16
            return "PVT_1"

    selection = put_github_selection(
        settings,
        owner="acme",
        repo="docs",
        project_owner="acme",
        project_number=16,
        connection_store=tokens,
        client_factory=lambda _token: FakeClient(),
    )
    assert selection.owner == "acme"
    assert selection.repo == "docs"
    assert selection.project_number == 16
    assert selection.connector_id
    stored = tokens.load()
    assert stored is not None
    assert stored.owner == "acme"
    assert stored.repo == "docs"
    assert stored.connector_id == selection.connector_id

    class SwapClient:
        def get_repository(self, owner: str, repo: str):
            return {"full_name": f"{owner}/{repo}"}

        def resolve_project_v2_id(self, owner_login: str, number: int) -> str:
            return f"PVT_{owner_login}_{number}"

    swapped = put_github_selection(
        settings,
        owner="acme",
        repo="handbook",
        project_owner=None,
        project_number=None,
        connection_store=tokens,
        client_factory=lambda _token: SwapClient(),
    )
    assert swapped.repo == "handbook"
    assert swapped.project_number is None
    assert swapped.connector_id == selection.connector_id
    stored_again = tokens.load()
    assert stored_again is not None
    assert stored_again.connector_id == selection.connector_id


def test_put_github_selection_allows_project_only(settings) -> None:
    from composition import put_github_selection

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.mutate(
        lambda _current: GitHubOAuthConnection(
            access_token="gho-access-secret",
            refresh_token=None,
            account_login="ada",
            owner="acme",
            repo="docs",
            project_owner=None,
            project_number=None,
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_removed=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )

    class FakeClient:
        def get_repository(self, owner: str, repo: str):
            raise AssertionError("repository should not be validated")

        def resolve_project_v2_id(self, owner_login: str, number: int) -> str:
            assert owner_login == "octocat"
            assert number == 19
            return "PVT_19"

    selection = put_github_selection(
        settings,
        owner=None,
        repo=None,
        project_owner="octocat",
        project_number=19,
        connection_store=tokens,
        client_factory=lambda _token: FakeClient(),
    )
    assert selection.owner is None
    assert selection.repo is None
    assert selection.project_owner == "octocat"
    assert selection.project_number == 19
    stored = tokens.load()
    assert stored is not None
    assert stored.owner is None
    assert stored.repo is None
    assert stored.project_number == 19


def test_github_status_setup_required_until_repo_or_project(settings) -> None:
    bare = replace(
        settings,
        github=replace(settings.github, owner=None, repo=None, project_owner=None, project_number=None),
    )
    tokens = GitHubOAuthConnectionStore(bare.github_oauth.token_path)
    tokens.mutate(
        lambda _current: GitHubOAuthConnection(
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
        )
    )
    status = github_status(bare)
    assert status.setup_required is True
    assert status.connection_state == "setup_required"

    tokens.mutate(
        lambda current: None
        if current is None
        else replace(
            current,
            project_owner="octocat",
            project_number=19,
        )
    )
    ready = github_status(bare)
    assert ready.setup_required is False
    assert ready.connection_state == "ready"
    assert ready.sync_scope == "octocat#19"

def test_list_github_repositories_maps_connector_error(settings) -> None:
    from composition import list_github_repositories
    from composition.errors import GitHubConnectorError
    from domain.errors import ConnectorError

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.mutate(
        lambda _current: GitHubOAuthConnection(
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
        )
    )

    class FailingClient:
        def list_repositories(self, *, page: int = 1):
            raise ConnectorError("vendor secret")

    with pytest.raises(GitHubConnectorError, match="GitHub request failed"):
        list_github_repositories(
            settings,
            page=1,
            connection_store=tokens,
            client_factory=lambda _token: FailingClient(),
        )


def test_list_github_projects_maps_connector_error(settings) -> None:
    from composition import list_github_projects
    from composition.errors import GitHubConnectorError
    from domain.errors import ConnectorError

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.mutate(
        lambda _current: GitHubOAuthConnection(
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
        )
    )

    class FailingClient:
        def list_projects(self, owner_login: str, *, after: str | None = None):
            raise ConnectorError("vendor secret")

    with pytest.raises(GitHubConnectorError, match="GitHub request failed"):
        list_github_projects(
            settings,
            owner_login="acme",
            connection_store=tokens,
            client_factory=lambda _token: FailingClient(),
        )


def _seed_github_connection(settings, *, owner, repo, project_owner, project_number):
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.mutate(
        lambda _current: GitHubOAuthConnection(
            access_token="gho-access-secret",
            refresh_token=None,
            account_login="ada",
            owner=owner,
            repo=repo,
            project_owner=project_owner,
            project_number=project_number,
            connector_id="connector-a",
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_removed=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )
    return tokens


def _github_catalog_row(
    source_id: str,
    *,
    connector_id: str | None = "connector-a",
):
    from datetime import UTC, datetime

    from domain.knowledge import (
        CatalogDocument,
        CatalogStatus,
        SourceReference,
        SourceType,
    )

    return CatalogDocument(
        reference=SourceReference(source_id, SourceType.GITHUB),
        file_name=f"{source_id.split(':')[-1]}.md",
        title=source_id,
        content_format="markdown",
        status=CatalogStatus.READY,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        chunk_count=1,
        error=None,
        revision="1",
        connector_id=connector_id,
    )


class _AcceptClient:
    def get_repository(self, owner: str, repo: str):
        return {"full_name": f"{owner}/{repo}"}

    def resolve_project_v2_id(self, owner_login: str, number: int) -> str:
        return f"PVT_{owner_login}_{number}"


def test_put_github_selection_clears_repo_purges_repo_docs_only(settings) -> None:
    from composition import put_github_selection
    from test.document_doubles import InMemoryDocumentCatalog
    from test.doubles import InMemoryVectorStore

    tokens = _seed_github_connection(
        settings,
        owner="acme",
        repo="docs",
        project_owner="acme",
        project_number=16,
    )
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_github_catalog_row("acme/docs:README.md"))
    catalog.upsert(_github_catalog_row("issue:ISSUE_1"))
    store = InMemoryVectorStore()

    put_github_selection(
        settings,
        owner=None,
        repo=None,
        project_owner="acme",
        project_number=16,
        connection_store=tokens,
        client_factory=lambda _token: _AcceptClient(),
        catalog=catalog,
        vector_store=store,
    )

    ids = {row.reference.source_id for row in catalog.all()}
    assert ids == {"issue:ISSUE_1"}


def test_put_github_selection_clears_project_purges_issue_docs_only(settings) -> None:
    from composition import put_github_selection
    from test.document_doubles import InMemoryDocumentCatalog
    from test.doubles import InMemoryVectorStore

    tokens = _seed_github_connection(
        settings,
        owner="acme",
        repo="docs",
        project_owner="acme",
        project_number=16,
    )
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_github_catalog_row("acme/docs:README.md"))
    catalog.upsert(_github_catalog_row("issue:ISSUE_1"))
    store = InMemoryVectorStore()

    put_github_selection(
        settings,
        owner="acme",
        repo="docs",
        project_owner=None,
        project_number=None,
        connection_store=tokens,
        client_factory=lambda _token: _AcceptClient(),
        catalog=catalog,
        vector_store=store,
    )

    ids = {row.reference.source_id for row in catalog.all()}
    assert ids == {"acme/docs:README.md"}


def test_put_github_selection_switch_repo_purges_old_prefix(settings) -> None:
    from composition import put_github_selection
    from test.document_doubles import InMemoryDocumentCatalog
    from test.doubles import InMemoryVectorStore

    tokens = _seed_github_connection(
        settings,
        owner="acme",
        repo="docs",
        project_owner=None,
        project_number=None,
    )
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_github_catalog_row("acme/docs:README.md"))
    catalog.upsert(_github_catalog_row("acme/handbook:GUIDE.md"))
    store = InMemoryVectorStore()

    put_github_selection(
        settings,
        owner="acme",
        repo="handbook",
        project_owner=None,
        project_number=None,
        connection_store=tokens,
        client_factory=lambda _token: _AcceptClient(),
        catalog=catalog,
        vector_store=store,
    )

    ids = {row.reference.source_id for row in catalog.all()}
    assert ids == {"acme/handbook:GUIDE.md"}


def test_put_github_selection_clears_both_purges_all_scoped_docs(settings) -> None:
    from composition import put_github_selection
    from test.document_doubles import InMemoryDocumentCatalog
    from test.doubles import InMemoryVectorStore

    tokens = _seed_github_connection(
        settings,
        owner="acme",
        repo="docs",
        project_owner="acme",
        project_number=16,
    )
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_github_catalog_row("acme/docs:README.md"))
    catalog.upsert(_github_catalog_row("issue:ISSUE_1"))
    catalog.upsert(
        _github_catalog_row("other/repo:kept.md", connector_id="connector-b")
    )
    store = InMemoryVectorStore()

    put_github_selection(
        settings,
        owner=None,
        repo=None,
        project_owner=None,
        project_number=None,
        connection_store=tokens,
        client_factory=lambda _token: _AcceptClient(),
        catalog=catalog,
        vector_store=store,
    )

    ids = {row.reference.source_id for row in catalog.all()}
    assert ids == {"other/repo:kept.md"}


def test_put_github_selection_unchanged_does_not_purge(settings) -> None:
    from composition import put_github_selection
    from test.document_doubles import InMemoryDocumentCatalog
    from test.doubles import InMemoryVectorStore

    tokens = _seed_github_connection(
        settings,
        owner="acme",
        repo="docs",
        project_owner="acme",
        project_number=16,
    )
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_github_catalog_row("acme/docs:README.md"))
    catalog.upsert(_github_catalog_row("issue:ISSUE_1"))
    store = InMemoryVectorStore()

    put_github_selection(
        settings,
        owner="acme",
        repo="docs",
        project_owner="acme",
        project_number=16,
        connection_store=tokens,
        client_factory=lambda _token: _AcceptClient(),
        catalog=catalog,
        vector_store=store,
    )

    ids = {row.reference.source_id for row in catalog.all()}
    assert ids == {"acme/docs:README.md", "issue:ISSUE_1"}
