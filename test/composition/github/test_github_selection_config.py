"""Config / env back-compat for multi-repo GitHub selection (#388 Slice 4)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from application.errors import InputRejectedError
from composition.github.models import GitHubRepoTarget
from composition.github.targets import resolve_target_file_rules
from infrastructure.config import GitHubOAuthSettings, GitHubSettings, load_settings
from infrastructure.connectors.github.oauth import (
    GitHubOAuthConnection,
    GitHubOAuthConnectionStore,
)


@pytest.fixture
def settings(tmp_path: Path):
    loaded = load_settings()
    return replace(
        loaded,
        github=GitHubSettings(
            owner="octo",
            repo="repo",
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


def test_omitted_extensions_use_github_extensions(settings) -> None:
    extensions, globs = resolve_target_file_rules(
        GitHubRepoTarget(owner="acme", repo="web"),
        workspace_extensions=settings.github.extensions,
    )
    assert extensions == frozenset({".md", ".py", ".txt"})
    assert globs == ()


def test_explicit_empty_extensions_do_not_fall_back(settings) -> None:
    extensions, globs = resolve_target_file_rules(
        GitHubRepoTarget(
            owner="acme",
            repo="ops",
            extensions=(),
            filename_globs=("Dockerfile",),
        ),
        workspace_extensions=settings.github.extensions,
    )
    assert extensions == frozenset()
    assert globs == ("Dockerfile",)


def test_max_repositories_env_overrides_bound(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GITHUB_MAX_REPOSITORIES", "2")
    loaded = load_settings()
    assert loaded.github.max_repositories == 2

    tokens = GitHubOAuthConnectionStore(tmp_path / "tok.json")
    tokens.mutate(
        lambda _c: GitHubOAuthConnection(
            access_token="gho",
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
    settings = replace(
        loaded,
        github_oauth=GitHubOAuthSettings(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="http://127.0.0.1:8000/api/v1/connectors/github/oauth/callback",
            frontend_redirect="http://localhost:3000/documents",
            token_path=tmp_path / "tok.json",
            state_path=tmp_path / "state.json",
            state_ttl_seconds=600,
        ),
    )

    from composition import put_github_selection

    class Client:
        def get_repository(self, owner: str, repo: str):
            return {"full_name": f"{owner}/{repo}"}

        def resolve_project_v2_id(self, owner_login: str, number: int) -> str:
            return "PVT"

    with pytest.raises(InputRejectedError, match="2"):
        put_github_selection(
            settings,
            repositories=(
                GitHubRepoTarget(owner="acme", repo="a"),
                GitHubRepoTarget(owner="acme", repo="b"),
                GitHubRepoTarget(owner="acme", repo="c"),
            ),
            connection_store=tokens,
            client_factory=lambda _t: Client(),
        )
