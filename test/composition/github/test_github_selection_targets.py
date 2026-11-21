"""Multi-repo GitHub selection contract (#388 Slice 1)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from application.errors import InputRejectedError
from infrastructure.config import GitHubOAuthSettings, GitHubSettings, load_settings
from infrastructure.connectors.github.oauth import (
    GitHubOAuthConnection,
    GitHubOAuthConnectionStore,
)
from test.document_doubles import InMemoryDocumentCatalog


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
    )
    base.update(overrides)
    tokens.mutate(lambda _current: GitHubOAuthConnection(**base))


class _AcceptClient:
    def get_repository(self, owner: str, repo: str):
        return {"full_name": f"{owner}/{repo}"}

    def resolve_project_v2_id(self, owner_login: str, number: int) -> str:
        return f"PVT_{owner_login}_{number}"


def test_legacy_flat_selection_becomes_one_element_repositories(settings) -> None:
    from composition import get_github_selection, put_github_selection
    from composition.github.models import GitHubRepoTarget

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    _grant(tokens)

    selection = put_github_selection(
        settings,
        owner="acme",
        repo="docs",
        connection_store=tokens,
        client_factory=lambda _token: _AcceptClient(),
    )

    assert selection.owner == "acme"
    assert selection.repo == "docs"
    assert selection.repositories == (
        GitHubRepoTarget(owner="acme", repo="docs"),
    )

    loaded = get_github_selection(settings, connection_store=tokens)
    assert loaded.repositories == (
        GitHubRepoTarget(owner="acme", repo="docs"),
    )
    assert loaded.repositories[0].extensions is None
    assert loaded.repositories[0].filename_globs is None


def test_put_two_targets_preserves_order(settings) -> None:
    from composition import put_github_selection
    from composition.github.models import GitHubRepoTarget

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    _grant(tokens)

    selection = put_github_selection(
        settings,
        repositories=(
            GitHubRepoTarget(owner="acme", repo="web"),
            GitHubRepoTarget(owner="acme", repo="orders"),
        ),
        connection_store=tokens,
        client_factory=lambda _token: _AcceptClient(),
    )

    assert [(t.owner, t.repo) for t in selection.repositories] == [
        ("acme", "web"),
        ("acme", "orders"),
    ]
    assert selection.owner == "acme"
    assert selection.repo == "web"


def test_duplicate_identity_case_insensitive_rejected(settings) -> None:
    from composition import put_github_selection
    from composition.github.models import GitHubRepoTarget

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    _grant(tokens)

    with pytest.raises(InputRejectedError, match="[Dd]uplicate"):
        put_github_selection(
            settings,
            repositories=(
                GitHubRepoTarget(owner="Acme", repo="Web"),
                GitHubRepoTarget(owner="acme", repo="web"),
            ),
            connection_store=tokens,
            client_factory=lambda _token: _AcceptClient(),
        )


def test_seventeenth_target_rejected_when_max_is_sixteen(settings) -> None:
    from composition import put_github_selection
    from composition.github.models import GitHubRepoTarget

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    _grant(tokens)
    settings = replace(
        settings,
        github=replace(settings.github, max_repositories=16),
    )
    targets = tuple(
        GitHubRepoTarget(owner="acme", repo=f"repo-{index}")
        for index in range(17)
    )

    with pytest.raises(InputRejectedError, match="16"):
        put_github_selection(
            settings,
            repositories=targets,
            connection_store=tokens,
            client_factory=lambda _token: _AcceptClient(),
        )


def test_unsafe_owner_repo_and_prefixes_rejected(settings) -> None:
    from composition import put_github_selection
    from composition.github.models import GitHubRepoTarget

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    _grant(tokens)

    with pytest.raises(InputRejectedError):
        put_github_selection(
            settings,
            repositories=(GitHubRepoTarget(owner="../x", repo="docs"),),
            connection_store=tokens,
            client_factory=lambda _token: _AcceptClient(),
        )

    with pytest.raises(InputRejectedError):
        put_github_selection(
            settings,
            repositories=(GitHubRepoTarget(owner="acme", repo="a/b"),),
            connection_store=tokens,
            client_factory=lambda _token: _AcceptClient(),
        )

    with pytest.raises(InputRejectedError):
        put_github_selection(
            settings,
            repositories=(
                GitHubRepoTarget(
                    owner="acme",
                    repo="docs",
                    include_prefixes=("../secrets",),
                ),
            ),
            connection_store=tokens,
            client_factory=lambda _token: _AcceptClient(),
        )


def test_safe_prefixes_normalized_on_put(settings) -> None:
    from composition import put_github_selection
    from composition.github.models import GitHubRepoTarget

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    _grant(tokens)

    selection = put_github_selection(
        settings,
        repositories=(
            GitHubRepoTarget(
                owner="acme",
                repo="docs",
                include_prefixes=(" src ", "docs"),
                exclude_prefixes=("build",),
            ),
        ),
        connection_store=tokens,
        client_factory=lambda _token: _AcceptClient(),
    )

    target = selection.repositories[0]
    assert target.include_prefixes == ("src/", "docs/")
    assert target.exclude_prefixes == ("build/",)


def test_omitted_null_and_empty_file_rules_round_trip(settings) -> None:
    from composition import put_github_selection
    from composition.github.models import GitHubRepoTarget

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    _grant(tokens)

    inherit = put_github_selection(
        settings,
        repositories=(GitHubRepoTarget(owner="acme", repo="a"),),
        connection_store=tokens,
        client_factory=lambda _token: _AcceptClient(),
    )
    assert inherit.repositories[0].extensions is None
    assert inherit.repositories[0].filename_globs is None

    explicit_empty = put_github_selection(
        settings,
        repositories=(
            GitHubRepoTarget(
                owner="acme",
                repo="b",
                extensions=(),
                filename_globs=(),
            ),
        ),
        connection_store=tokens,
        client_factory=lambda _token: _AcceptClient(),
    )
    assert explicit_empty.repositories[0].extensions == ()
    assert explicit_empty.repositories[0].filename_globs == ()

    explicit = put_github_selection(
        settings,
        repositories=(
            GitHubRepoTarget(
                owner="acme",
                repo="c",
                extensions=(".TSX", ".tsx", "robot"),
                filename_globs=(" Dockerfile ", "Dockerfile"),
            ),
        ),
        connection_store=tokens,
        client_factory=lambda _token: _AcceptClient(),
    )
    assert explicit.repositories[0].extensions == (".tsx", ".robot")
    assert explicit.repositories[0].filename_globs == ("Dockerfile",)


def test_config_only_change_does_not_purge_identity_docs(settings) -> None:
    from datetime import UTC, datetime

    from composition import put_github_selection
    from composition.github.models import GitHubRepoTarget
    from domain.knowledge import (
        CatalogDocument,
        CatalogStatus,
        SourceReference,
        SourceType,
    )

    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    _grant(tokens, owner="acme", repo="docs", connector_id="gh-1")
    catalog = InMemoryDocumentCatalog()
    ref = SourceReference("acme/docs:README.md", SourceType.GITHUB)
    catalog.upsert(
        CatalogDocument(
            reference=ref,
            file_name="README.md",
            title="README",
            content_format="markdown",
            status=CatalogStatus.READY,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            chunk_count=1,
            error=None,
            revision="1",
            connector_id="gh-1",
        )
    )

    put_github_selection(
        settings,
        repositories=(
            GitHubRepoTarget(
                owner="acme",
                repo="docs",
                extensions=(".md",),
            ),
        ),
        connection_store=tokens,
        client_factory=lambda _token: _AcceptClient(),
        catalog=catalog,
    )

    assert catalog.get(ref) is not None
