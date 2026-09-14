"""Repository tree adapter for GitHub knowledge documents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from domain.errors import ConnectorError
from domain.knowledge import (
    ConnectorDocument,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.connectors.github.client import GitHubClient, GitHubEmptyRepositoryError

_MSG_REQUEST_FAILED = "The GitHub request failed."
_MSG_UNREADABLE = "A GitHub file could not be read as text."
_MSG_EMPTY = "A GitHub file was empty."
_DEFAULT_TEXT_EXTENSIONS = frozenset(
    {
        ".csv",
        ".json",
        ".md",
        ".markdown",
        ".py",
        ".rst",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)
_BINARY_EXTENSIONS = frozenset(
    {
        ".7z",
        ".avif",
        ".bin",
        ".bmp",
        ".dll",
        ".dmg",
        ".doc",
        ".docx",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".pdf",
        ".png",
        ".so",
        ".webp",
        ".zip",
    }
)
_SKIP_SEGMENTS = frozenset(
    {
        ".git",
        ".hg",
        ".next",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "vendor",
    }
)
_GENERATED_SUFFIXES = (".min.css", ".min.js", ".map")


@dataclass(frozen=True, slots=True)
class GitHubRepoConfig:
    """Repository listing configuration."""

    owner: str
    repo: str
    ref: str = "HEAD"
    include_prefixes: Sequence[str] = ()
    exclude_prefixes: Sequence[str] = ()
    text_extensions: frozenset[str] = field(default_factory=lambda: _DEFAULT_TEXT_EXTENSIONS)
    max_size_bytes: int = 1_000_000
    connector_id: str | None = None


class GitHubRepoDocuments:
    """Map a GitHub repository tree and blobs to connector documents."""

    def __init__(self, client: GitHubClient, config: GitHubRepoConfig) -> None:
        self._client = client
        self._config = config

    def list_documents(self) -> Sequence[ConnectorDocument]:
        try:
            commit_sha = self._client.resolve_commit_sha(
                self._config.owner,
                self._config.repo,
                self._config.ref,
            )
        except GitHubEmptyRepositoryError:
            return ()
        payload = self._client.get_git_tree(
            self._config.owner,
            self._config.repo,
            commit_sha,
            recursive=True,
        )
        tree = payload.get("tree")
        if not isinstance(tree, Sequence) or isinstance(tree, (str, bytes)):
            raise ConnectorError(_MSG_REQUEST_FAILED)
        documents: list[ConnectorDocument] = []
        for entry in tree:
            document = self._document_from_entry(entry, commit_sha)
            if document is not None:
                documents.append(document)
        return tuple(documents)

    def fetch_document(self, document: ConnectorDocument) -> SourceDocument:
        path = document.extra.get("path") or _path_from_source_id(document.source_id)
        blob_sha = document.extra.get("blob_sha") or document.revision
        commit_sha = document.extra.get("commit_sha")
        if path is None or not blob_sha or commit_sha is None:
            raise ConnectorError(_MSG_REQUEST_FAILED)
        content = self._client.get_blob_content(
            self._config.owner,
            self._config.repo,
            blob_sha,
        )
        if len(content) > self._config.max_size_bytes:
            raise ConnectorError(_MSG_REQUEST_FAILED)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ConnectorError(_MSG_UNREADABLE) from error
        if not text.strip():
            raise ConnectorError(_MSG_EMPTY)
        return SourceDocument(
            SourceMetadata(
                reference=document.reference,
                title=Path(path).stem,
                provider="github",
                content_format=_content_format(path),
                extra={
                    "file_name": document.file_name,
                    "github_owner": self._config.owner,
                    "github_repo": self._config.repo,
                    "github_path": path,
                    "github_commit_sha": commit_sha,
                    "github_blob_sha": blob_sha,
                    "github_url": _provenance_url(
                        self._config.owner,
                        self._config.repo,
                        commit_sha,
                        path,
                    ),
                    "byte_size": str(len(content)),
                    **_connector_extra(self._config.connector_id),
                },
            ),
            text,
        )

    def _document_from_entry(
        self,
        entry: object,
        commit_sha: str,
    ) -> ConnectorDocument | None:
        if not isinstance(entry, Mapping):
            raise ConnectorError(_MSG_REQUEST_FAILED)
        if entry.get("type") != "blob":
            return None
        path = _required_text(entry, "path")
        blob_sha = _required_text(entry, "sha")
        size = _optional_size(entry.get("size"))
        if size is not None and size == 0:
            return None
        if size is not None and size > self._config.max_size_bytes:
            return None
        if not _path_allowed(path, self._config):
            return None
        return ConnectorDocument(
            reference=SourceReference(
                f"{self._config.owner}/{self._config.repo}:{path}",
                SourceType.GITHUB,
            ),
            file_name=Path(path).name,
            revision=blob_sha,
            extra={
                "github_kind": "repo",
                "owner": self._config.owner,
                "repo": self._config.repo,
                "path": path,
                "commit_sha": commit_sha,
                "blob_sha": blob_sha,
                "url": _provenance_url(self._config.owner, self._config.repo, commit_sha, path),
                **({"size": str(size)} if size is not None else {}),
                **_connector_extra(self._config.connector_id),
            },
        )


def _connector_extra(connector_id: str | None) -> dict[str, str]:
    if isinstance(connector_id, str) and connector_id.strip():
        return {"connector_id": connector_id.strip()}
    return {}


def _path_allowed(path: str, config: GitHubRepoConfig) -> bool:
    if any(path.startswith(prefix) for prefix in config.exclude_prefixes):
        return False
    if config.include_prefixes and not any(
        path.startswith(prefix) for prefix in config.include_prefixes
    ):
        return False
    lowered = path.lower()
    suffix = Path(path).suffix.lower()
    if suffix in _BINARY_EXTENSIONS or suffix not in config.text_extensions:
        return False
    if lowered.endswith(_GENERATED_SUFFIXES):
        return False
    parts = tuple(part.lower() for part in Path(path).parts)
    return not any(part in _SKIP_SEGMENTS for part in parts)


def _provenance_url(owner: str, repo: str, commit_sha: str, path: str) -> str:
    return f"https://github.com/{owner}/{repo}/blob/{commit_sha}/{path}"


def _content_format(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    return suffix.removeprefix(".") or "text"


def _path_from_source_id(source_id: str) -> str | None:
    if ":" not in source_id:
        return None
    return source_id.split(":", 1)[1] or None


def _required_text(entry: Mapping[str, object], field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConnectorError(_MSG_REQUEST_FAILED)
    return value


def _optional_size(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
