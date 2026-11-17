"""HTTP contracts for anonymous public GitHub Issue Test Design (#302)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from composition import container as composition_container
from composition.github.connection import github_status
from domain.errors import ConnectorNotFoundError
from infrastructure.config import DomainToolSettings, GitHubOAuthSettings, load_settings
from infrastructure.connectors.github.oauth import (
    GitHubOAuthConnection,
    GitHubOAuthConnectionStore,
)
from presentation.http.app import create_app
from presentation.http.deps import get_github_status, get_settings, get_test_design_facade
from test.composition.test_design.test_design_fakes import build_fake_facade


def _issue_payload() -> dict[str, object]:
    return {
        "node_id": "I_kwDOExample",
        "number": 7,
        "title": "Login",
        "body": "Acceptance criteria live here.",
        "state": "open",
        "labels": [],
        "assignees": [],
        "milestone": None,
        "created_at": "2026-09-13T12:00:00Z",
        "closed_at": None,
        "html_url": "https://github.com/acme/app/issues/7",
        "updated_at": "2026-09-14T12:00:00Z",
        "repository_url": "https://api.github.com/repos/acme/app",
        "repository": {"full_name": "acme/app"},
    }


class _ScriptedClient:
    def __init__(
        self,
        *,
        payload: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.error = error

    def get_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, object]:
        if self.error is not None:
            raise self.error
        assert self.payload is not None
        return self.payload


def _settings(tmp_path: Path):
    loaded = load_settings()
    return replace(
        loaded,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
        github_oauth=GitHubOAuthSettings(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="http://127.0.0.1:8000/api/v1/connectors/github/oauth/callback",
            frontend_redirect="http://localhost:3000/documents",
            token_path=tmp_path / "github-oauth-connection.json",
            state_path=tmp_path / "github-oauth-state.json",
            state_ttl_seconds=600,
        ),
        github=replace(loaded.github, token="ghp_CONFIGURED_PAT_MUST_NOT_APPEAR"),
    )


def _grant(*, reauthorization_required: bool = False) -> GitHubOAuthConnection:
    return GitHubOAuthConnection(
        access_token="gho-access",
        refresh_token="ghr-refresh",
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
        reauthorization_required=reauthorization_required,
    )


def _client(
    tmp_path: Path,
    *,
    payload: dict[str, object] | None = None,
    error: Exception | None = None,
    grant: GitHubOAuthConnection | None = None,
) -> tuple[TestClient, GitHubOAuthConnectionStore]:
    settings = _settings(tmp_path)
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    if grant is not None:
        tokens.save(grant)
    registry = composition_container.build_test_design_sources(
        settings,
        connection_store=tokens,
        client_factory=lambda _token: _ScriptedClient(payload=payload, error=error),
    )
    facade = build_fake_facade(tmp_path, sources=registry)
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_test_design_facade] = lambda: facade
    app.dependency_overrides[get_github_status] = lambda: github_status(settings)
    return TestClient(app, raise_server_exceptions=False), tokens


def _create(http: TestClient):
    return http.post(
        "/api/v1/test-design/drafts",
        json={
            "conversation_id": "conv-anon",
            "source_locator": {"provider": "github", "locator": "acme/app#7"},
        },
    )


def test_http_disconnected_public_issue_creates_draft(tmp_path: Path) -> None:
    http, tokens = _client(tmp_path, payload=_issue_payload())
    response = _create(http)

    assert response.status_code == 200
    assert response.json()["ticket_identifier"] == "acme/app#7"
    assert tokens.load() is None
    status = http.get("/api/v1/connectors/github")
    assert status.status_code == 200
    assert status.json()["connected"] is False
    assert status.json()["reauthorization_required"] is False


def test_http_disconnected_unreadable_is_github_not_connected(tmp_path: Path) -> None:
    http, _tokens = _client(tmp_path, error=ConnectorNotFoundError("missing"))
    response = _create(http)

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "github_not_connected"
    assert body["detail"] == "GitHub is not connected."
    assert "private" not in body["detail"].casefold()
    assert "not found" not in body["detail"].casefold()


def test_http_reauth_public_issue_creates_without_clearing_flag(
    tmp_path: Path,
) -> None:
    http, tokens = _client(
        tmp_path,
        payload=_issue_payload(),
        grant=_grant(reauthorization_required=True),
    )
    response = _create(http)

    assert response.status_code == 200
    saved = tokens.load()
    assert saved is not None
    assert saved.reauthorization_required is True
    status = http.get("/api/v1/connectors/github")
    assert status.status_code == 200
    assert status.json()["connected"] is True
    assert status.json()["reauthorization_required"] is True


def test_http_reauth_unreadable_is_github_reauthorization_required(
    tmp_path: Path,
) -> None:
    http, tokens = _client(
        tmp_path,
        error=ConnectorNotFoundError("missing"),
        grant=_grant(reauthorization_required=True),
    )
    response = _create(http)

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "github_reauthorization_required"
    assert "Connect again" in body["detail"]
    saved = tokens.load()
    assert saved is not None
    assert saved.reauthorization_required is True
