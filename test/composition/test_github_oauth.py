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
from infrastructure.connectors.github_oauth import (
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
