"""GitHub Issues contract harness over the production source composition."""

from __future__ import annotations

from pathlib import Path

import pytest

from composition import container as composition_container
from composition.test_design.sources import TestDesignSource
from domain.errors import ConnectorAuthError, ConnectorNotFoundError
from infrastructure.config import load_settings
from infrastructure.connectors.github.client import HttpGitHubClient
from infrastructure.connectors.github.oauth import (
    GitHubOAuthConnection,
    GitHubOAuthConnectionStore,
    GitHubOAuthGrant,
    HttpGitHubOAuthGateway,
)


class _ScriptedIssueClient:
    def __init__(self, harness: GitHubContractHarness) -> None:
        self._harness = harness

    def get_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, object]:
        return self._harness._respond(owner, repo, issue_number)


class _RefreshingGateway:
    def __init__(self) -> None:
        self.refreshes = 0

    def refresh(self, refresh_token: str) -> GitHubOAuthGrant:
        self.refreshes += 1
        return GitHubOAuthGrant(
            access_token=f"gho-refreshed-{self.refreshes}",
            refresh_token=refresh_token,
        )


def _refuse_construction(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("contract tests must not build a real GitHub HTTP client")


class GitHubContractHarness:
    """``SourceContractHarness`` for GitHub Issues."""

    provider = "github"
    source_type = "github"
    raw_locators = (
        "acme/app#7",
        " acme/app#7 ",
        "https://github.com/acme/app/issues/7",
    )
    canonical_locator = "acme/app#7"
    invalid_locators = ("", "7", "https://github.com/acme/app/pull/7")

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(HttpGitHubClient, "__init__", _refuse_construction)
        monkeypatch.setattr(HttpGitHubOAuthGateway, "__init__", _refuse_construction)
        self._grants = GitHubOAuthConnectionStore(tmp_path / "github-grant.json")
        self._gateway = _RefreshingGateway()
        self._calls = 0
        self._body = "Acceptance criteria: login, lockout, password length."
        self._item_id = "item-1"
        self._failure: Exception | None = None
        self._grants.save(_grant())

    @property
    def upstream_calls(self) -> int:
        return self._calls

    def source(self) -> TestDesignSource:
        return composition_container.build_test_design_sources(
            load_settings(),
            connection_store=self._grants,
            oauth_gateway=self._gateway,
            client_factory=lambda _token: _ScriptedIssueClient(self),
        ).resolve(self.provider)

    def serve(self, body: str, *, item_id: str = "item-1") -> None:
        self._body = body
        self._item_id = item_id
        self._failure = None

    def disconnect(self) -> None:
        self._grants.clear()

    def reject_auth(self) -> None:
        self._failure = ConnectorAuthError("The GitHub credentials were rejected.")

    def fail_not_found(self) -> None:
        self._failure = ConnectorNotFoundError("The GitHub resource was not found.")

    def _respond(self, owner: str, repo: str, number: int) -> dict[str, object]:
        self._calls += 1
        if self._failure is not None:
            raise self._failure
        return {
            "number": number,
            "node_id": self._item_id,
            "title": "Login",
            "body": self._body,
            "updated_at": "2026-09-14T12:00:00Z",
            "html_url": f"https://github.com/{owner}/{repo}/issues/{number}",
            "repository": {"full_name": f"{owner}/{repo}"},
            "state": "open",
            "labels": [],
        }


def _grant() -> GitHubOAuthConnection:
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
        reauthorization_required=False,
    )
