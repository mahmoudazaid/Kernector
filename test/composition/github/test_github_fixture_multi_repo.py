"""#371 fixture: four acme/proj-* repos sync together (#388 Slice 6)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from application.contracts import IngestRequest, IngestResponse
from composition import put_github_selection, sync_github_oauth
from composition import container as composition_container
from composition.github import sync as github_sync
from composition.github.models import GitHubRepoTarget
from infrastructure.config import GitHubOAuthSettings, GitHubSettings, load_settings
from infrastructure.connectors.github.connector import GitHubKnowledgeConnector
from infrastructure.connectors.github.oauth import (
    GitHubOAuthConnection,
    GitHubOAuthConnectionStore,
)
from infrastructure.connectors.github.repo_documents import (
    GitHubRepoConfig,
    GitHubRepoDocuments,
)
from test.document_doubles import InMemoryDocumentCatalog
from test.doubles import InMemoryVectorStore

FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "project_intelligence"
    / "v1"
    / "acme"
)

REPOS = ("proj-web", "proj-orders", "proj-tests", "proj-e2e")


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CHROMA_PERSIST_PATH", str(tmp_path / "chroma"))
    loaded = load_settings()
    return replace(
        loaded,
        github=GitHubSettings(
            extensions=(".md", ".py", ".txt", ".tsx", ".ts", ".robot", ".yml"),
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


class FixtureGitHubClient:
    def __init__(self, root: Path) -> None:
        self._root = root

    def resolve_commit_sha(self, owner: str, repo: str, ref: str) -> str:
        return f"commit-{owner}-{repo}"

    def get_git_tree(
        self,
        owner: str,
        repo: str,
        tree_sha: str,
        *,
        recursive: bool = True,
    ) -> dict[str, object]:
        base = self._root / repo
        tree: list[dict[str, object]] = []
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            tree.append(
                {
                    "type": "blob",
                    "path": rel,
                    "sha": f"blob-{repo}-{rel}",
                    "size": path.stat().st_size or 1,
                }
            )
        return {"tree": tree, "truncated": False}

    def get_blob_content(self, owner: str, repo: str, blob_sha: str) -> bytes:
        # blob-{repo}-{rel}
        prefix = f"blob-{repo}-"
        assert blob_sha.startswith(prefix)
        rel = blob_sha[len(prefix) :]
        return (self._root / repo / rel).read_bytes()

    def get_repository(self, owner: str, repo: str):
        return {"full_name": f"{owner}/{repo}"}

    def resolve_project_v2_id(self, owner_login: str, number: int) -> str:
        return f"PVT_{owner_login}_{number}"


class _Ingest:
    def execute(self, request: IngestRequest) -> IngestResponse:
        return IngestResponse(
            accepted_ids=[document.source_id for document in request.documents],
            chunk_count=1,
        )


def _targets() -> tuple[GitHubRepoTarget, ...]:
    return (
        GitHubRepoTarget(
            owner="acme",
            repo="proj-web",
            extensions=(".tsx", ".ts", ".json"),
        ),
        GitHubRepoTarget(
            owner="acme",
            repo="proj-orders",
            extensions=(".py", ".toml", ".yml"),
            filename_globs=("Dockerfile",),
        ),
        GitHubRepoTarget(
            owner="acme",
            repo="proj-tests",
            extensions=(".robot", ".resource", ".txt"),
        ),
        GitHubRepoTarget(
            owner="acme",
            repo="proj-e2e",
            extensions=(".ts", ".json"),
        ),
    )


def test_four_fixture_repos_sync_and_selective_purge(
    settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert FIXTURE_ROOT.is_dir()
    tokens = GitHubOAuthConnectionStore(settings.github_oauth.token_path)
    tokens.mutate(
        lambda _c: GitHubOAuthConnection(
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
            connector_id="connector-fixture",
        )
    )
    client = FixtureGitHubClient(FIXTURE_ROOT)
    put_github_selection(
        settings,
        repositories=_targets(),
        connection_store=tokens,
        client_factory=lambda _token: client,
    )

    catalog = InMemoryDocumentCatalog()
    store = InMemoryVectorStore()
    monkeypatch.setattr(
        composition_container,
        "build_ingest_knowledge",
        lambda _settings, *, vector_store=None: _Ingest(),
    )

    def build(sync_settings, *, token: str):
        github = sync_settings.github
        return GitHubKnowledgeConnector(
            repo_documents=GitHubRepoDocuments(
                client,
                GitHubRepoConfig(
                    owner=github.owner or "",
                    repo=github.repo or "",
                    ref=github.ref,
                    include_prefixes=github.include_paths,
                    exclude_prefixes=github.exclude_paths,
                    text_extensions=frozenset(github.extensions),
                    filename_globs=tuple(github.filename_globs),
                    max_size_bytes=github.max_file_bytes,
                    connector_id=github.connector_id,
                ),
            )
        )

    monkeypatch.setattr(github_sync, "build_github_oauth_connector", build)

    result = sync_github_oauth(
        settings,
        catalog=catalog,
        vector_store=store,
        connection_store=tokens,
    )

    ids = {row.reference.source_id for row in catalog.all()}
    for repo in REPOS:
        assert any(source_id.startswith(f"acme/{repo}:") for source_id in ids), repo
    assert any("proj-web:" in source_id and source_id.endswith(".tsx") for source_id in ids)
    assert "acme/proj-orders:Dockerfile" in ids
    assert not any(source_id.endswith(".env") for source_id in ids)
    assert result.ingested_count >= 4

    put_github_selection(
        settings,
        repositories=tuple(t for t in _targets() if t.repo != "proj-e2e"),
        connection_store=tokens,
        client_factory=lambda _token: client,
        catalog=catalog,
        vector_store=store,
    )
    remaining = {row.reference.source_id for row in catalog.all()}
    assert not any(source_id.startswith("acme/proj-e2e:") for source_id in remaining)
    assert any(source_id.startswith("acme/proj-web:") for source_id in remaining)
    assert any(source_id.startswith("acme/proj-orders:") for source_id in remaining)
    assert any(source_id.startswith("acme/proj-tests:") for source_id in remaining)

    # Narrow globs on orders should not touch other repos at put time.
    before = set(remaining)
    put_github_selection(
        settings,
        repositories=(
            GitHubRepoTarget(
                owner="acme",
                repo="proj-web",
                extensions=(".tsx", ".ts", ".json"),
            ),
            GitHubRepoTarget(
                owner="acme",
                repo="proj-orders",
                extensions=(),
                filename_globs=("Dockerfile",),
            ),
            GitHubRepoTarget(
                owner="acme",
                repo="proj-tests",
                extensions=(".robot", ".resource", ".txt"),
            ),
        ),
        connection_store=tokens,
        client_factory=lambda _token: client,
        catalog=catalog,
        vector_store=store,
    )
    assert {row.reference.source_id for row in catalog.all()} == before

    sync_github_oauth(
        settings,
        catalog=catalog,
        vector_store=store,
        connection_store=tokens,
    )
    after = {row.reference.source_id for row in catalog.all()}
    assert "acme/proj-orders:Dockerfile" in after
    assert any(source_id.startswith("acme/proj-web:") for source_id in after)
    assert any(source_id.startswith("acme/proj-tests:") for source_id in after)
