"""GitHub OAuth stores and gateway helpers — no live GitHub."""

from __future__ import annotations

import os
from pathlib import Path

from infrastructure.connectors.github_oauth import (
    GitHubOAuthConnection,
    GitHubOAuthConnectionStore,
    GitHubOAuthStateStore,
)


def test_state_is_single_use(tmp_path: Path) -> None:
    store = GitHubOAuthStateStore(tmp_path / "github-oauth-state.json", ttl_seconds=600)
    state = store.issue()

    assert store.consume(state) is True
    assert store.consume(state) is False


def test_connection_store_redacts_repr_and_writes_0600(tmp_path: Path) -> None:
    path = tmp_path / "github-oauth-connection.json"
    store = GitHubOAuthConnectionStore(path)
    store.save(
        GitHubOAuthConnection(
            access_token="gho-access-secret",
            refresh_token="ghr-refresh-secret",
            account_login="ada",
            owner="octo",
            repo="repo",
            project_owner="octo",
            project_number=7,
            last_synced_at=None,
            last_sync_new=None,
            last_sync_updated=None,
            last_sync_unchanged=None,
            last_sync_removed=None,
            last_sync_failed=None,
            reauthorization_required=False,
        )
    )

    loaded = store.load()
    assert loaded is not None
    assert loaded.account_login == "ada"
    assert loaded.project_number == 7
    assert "gho-access-secret" not in repr(loaded)
    assert "ghr-refresh-secret" not in repr(loaded)
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"


def test_connection_store_clear(tmp_path: Path) -> None:
    path = tmp_path / "github-oauth-connection.json"
    store = GitHubOAuthConnectionStore(path)
    store.save(
        GitHubOAuthConnection(
            access_token="gho-access-secret",
            refresh_token=None,
            account_login=None,
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

    store.clear()

    assert store.load() is None
