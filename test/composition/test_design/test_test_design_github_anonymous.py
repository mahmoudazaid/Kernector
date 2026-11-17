"""Anonymous public GitHub Issue reads for Test Design (#302)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from application.errors import (
    GitHubNotConnectedError,
    GitHubReauthorizationRequiredError,
    InsufficientEvidenceError,
)
from composition import container as composition_container
from composition.test_design.errors import TestDesignValidationError
from domain.errors import (
    ConnectorAuthError,
    ConnectorNetworkError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    ConnectorUnavailableError,
    ConnectorError,
)
from domain.knowledge import SourceLocator
from infrastructure.config import (
    DomainToolSettings,
    GitHubOAuthSettings,
    Settings,
    load_settings,
)
from infrastructure.connectors.github.oauth import (
    GitHubOAuthConnection,
    GitHubOAuthConnectionStore,
)


def _settings(tmp_path: Path) -> Settings:
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


def _grant(
    *,
    access_token: str | None = "gho-access",
    reauthorization_required: bool = False,
    owner: str | None = None,
    repo: str | None = None,
) -> GitHubOAuthConnection:
    return GitHubOAuthConnection(
        access_token=access_token or "",
        refresh_token="ghr-refresh",
        account_login="ada",
        owner=owner,
        repo=repo,
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


def _issue_payload(
    owner: str = "acme",
    repo: str = "app",
    number: int = 7,
    *,
    body: str = "Acceptance criteria live here.",
    pull_request: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "node_id": "I_kwDOExample",
        "number": number,
        "title": "Login",
        "body": body,
        "state": "open",
        "labels": [],
        "assignees": [],
        "milestone": None,
        "created_at": "2026-09-13T12:00:00Z",
        "closed_at": None,
        "html_url": f"https://github.com/{owner}/{repo}/issues/{number}",
        "updated_at": "2026-09-14T12:00:00Z",
        "repository_url": f"https://api.github.com/repos/{owner}/{repo}",
        "repository": {"full_name": f"{owner}/{repo}"},
    }
    if pull_request is not None:
        payload["pull_request"] = pull_request
    return payload


class _ScriptedClient:
    def __init__(
        self,
        *,
        token: str | None,
        payload: dict[str, object] | None = None,
        error: Exception | None = None,
        tokens_seen: list[str | None] | None = None,
    ) -> None:
        self.token = token
        self.payload = payload
        self.error = error
        self.tokens_seen = tokens_seen

    def get_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, object]:
        if self.tokens_seen is not None:
            self.tokens_seen.append(self.token)
        if self.error is not None:
            raise self.error
        assert self.payload is not None
        return self.payload


def _source(
    tmp_path: Path,
    *,
    store: GitHubOAuthConnectionStore | None = None,
    client_factory=None,
):
    settings = _settings(tmp_path)
    tokens = store or GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    return composition_container.build_test_design_sources(
        settings,
        connection_store=tokens,
        client_factory=client_factory,
    ).resolve("github"), tokens


def test_disconnected_public_issue_fetches_anonymously(tmp_path: Path) -> None:
    seen: list[str | None] = []

    def factory(token: str | None):
        return _ScriptedClient(
            token=token,
            payload=_issue_payload(),
            tokens_seen=seen,
        )

    source, tokens = _source(tmp_path, client_factory=factory)
    document = source.reader().fetch(
        SourceLocator(provider="github", locator="acme/app#7")
    )

    assert document.reference.source_id == "issue:I_kwDOExample"
    assert "Acceptance criteria" in document.content
    assert seen == [None]
    assert tokens.load() is None


def test_disconnected_unreadable_is_not_connected(tmp_path: Path) -> None:
    def factory(token: str | None):
        return _ScriptedClient(
            token=token,
            error=ConnectorNotFoundError("missing"),
        )

    source, _tokens = _source(tmp_path, client_factory=factory)

    with pytest.raises(GitHubNotConnectedError):
        source.reader().fetch(SourceLocator(provider="github", locator="acme/app#7"))


def test_disconnected_permission_denied_is_not_connected(tmp_path: Path) -> None:
    def factory(token: str | None):
        return _ScriptedClient(
            token=token,
            error=ConnectorAuthError("forbidden"),
        )

    source, _tokens = _source(tmp_path, client_factory=factory)

    with pytest.raises(GitHubNotConnectedError):
        source.reader().fetch(SourceLocator(provider="github", locator="acme/app#7"))


@pytest.mark.parametrize(
    "error",
    [
        ConnectorRateLimitError("rate"),
        ConnectorTimeoutError("timeout"),
        ConnectorNetworkError("network"),
        ConnectorUnavailableError("unavailable"),
        ConnectorError("malformed"),
    ],
)
def test_disconnected_preserves_non_permission_errors(
    tmp_path: Path, error: Exception
) -> None:
    def factory(token: str | None):
        return _ScriptedClient(token=token, error=error)

    source, _tokens = _source(tmp_path, client_factory=factory)

    with pytest.raises(type(error)):
        source.reader().fetch(SourceLocator(provider="github", locator="acme/app#7"))


def test_anonymous_empty_body_is_insufficient_evidence(tmp_path: Path) -> None:
    def factory(token: str | None):
        return _ScriptedClient(
            token=token,
            payload=_issue_payload(body="   "),
        )

    source, _tokens = _source(tmp_path, client_factory=factory)

    with pytest.raises(InsufficientEvidenceError):
        source.reader().fetch(SourceLocator(provider="github", locator="acme/app#7"))


def test_anonymous_pull_request_is_validation_error(tmp_path: Path) -> None:
    def factory(token: str | None):
        return _ScriptedClient(
            token=token,
            payload=_issue_payload(pull_request={"url": "https://api.github.com/..."}),
        )

    source, _tokens = _source(tmp_path, client_factory=factory)

    with pytest.raises(TestDesignValidationError):
        source.reader().fetch(SourceLocator(provider="github", locator="acme/app#7"))


def test_anonymous_locator_mismatch_is_validation_error(tmp_path: Path) -> None:
    def factory(token: str | None):
        return _ScriptedClient(
            token=token,
            payload=_issue_payload(number=99),
        )

    source, _tokens = _source(tmp_path, client_factory=factory)

    with pytest.raises(TestDesignValidationError):
        source.reader().fetch(SourceLocator(provider="github", locator="acme/app#7"))


def test_usable_token_without_hub_selection_uses_authenticated_path(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.save(_grant(owner=None, repo=None))
    seen: list[str | None] = []

    def factory(token: str | None):
        return _ScriptedClient(
            token=token,
            payload=_issue_payload(),
            tokens_seen=seen,
        )

    source, _ = _source(tmp_path, store=tokens, client_factory=factory)
    document = source.reader().fetch(
        SourceLocator(provider="github", locator="acme/app#7")
    )

    assert document.reference.source_id == "issue:I_kwDOExample"
    assert seen == ["gho-access"]


def test_blank_token_uses_anonymous_path(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.save(_grant(access_token="   "))
    seen: list[str | None] = []

    def factory(token: str | None):
        return _ScriptedClient(
            token=token,
            payload=_issue_payload(),
            tokens_seen=seen,
        )

    source, stored = _source(tmp_path, store=tokens, client_factory=factory)
    source.reader().fetch(SourceLocator(provider="github", locator="acme/app#7"))

    assert seen == [None]
    assert stored.load() is not None


def test_reauth_required_public_issue_fetches_anonymously(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.save(_grant(reauthorization_required=True))
    seen: list[str | None] = []

    def factory(token: str | None):
        return _ScriptedClient(
            token=token,
            payload=_issue_payload(),
            tokens_seen=seen,
        )

    source, stored = _source(tmp_path, store=tokens, client_factory=factory)
    document = source.reader().fetch(
        SourceLocator(provider="github", locator="acme/app#7")
    )

    assert document.reference.source_id == "issue:I_kwDOExample"
    assert seen == [None]
    saved = stored.load()
    assert saved is not None
    assert saved.reauthorization_required is True
    assert saved.access_token == "gho-access"


def test_reauth_required_unreadable_stays_reauthorization_required(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.save(_grant(reauthorization_required=True))

    def factory(token: str | None):
        return _ScriptedClient(
            token=token,
            error=ConnectorNotFoundError("missing"),
        )

    source, stored = _source(tmp_path, store=tokens, client_factory=factory)

    with pytest.raises(GitHubReauthorizationRequiredError):
        source.reader().fetch(SourceLocator(provider="github", locator="acme/app#7"))

    saved = stored.load()
    assert saved is not None
    assert saved.reauthorization_required is True


def test_authenticated_failure_does_not_fall_back_to_anonymous(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.save(
        GitHubOAuthConnection(
            access_token="gho-access",
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
    seen: list[str | None] = []

    def factory(token: str | None):
        return _ScriptedClient(
            token=token,
            error=ConnectorAuthError("expired"),
            tokens_seen=seen,
        )

    source, stored = _source(tmp_path, store=tokens, client_factory=factory)

    with pytest.raises(GitHubReauthorizationRequiredError):
        source.reader().fetch(SourceLocator(provider="github", locator="acme/app#7"))

    assert None not in seen
    assert all(token == "gho-access" for token in seen)
    saved = stored.load()
    assert saved is not None
    assert saved.reauthorization_required is True


def test_anonymous_factory_never_receives_configured_pat(tmp_path: Path) -> None:
    seen: list[str | None] = []

    def factory(token: str | None):
        assert token is None
        seen.append(token)
        return _ScriptedClient(token=token, payload=_issue_payload())

    source, _ = _source(tmp_path, client_factory=factory)
    source.reader().fetch(SourceLocator(provider="github", locator="acme/app#7"))
    assert seen == [None]
