"""Combined GitHub KnowledgeConnector."""

from __future__ import annotations

from collections.abc import Sequence

from domain.errors import ConnectorError
from domain.knowledge import ConnectorDocument, SourceDocument
from domain.ports import KnowledgeConnector
from infrastructure.connectors.github.client import GitHubClient, GitHubConfigError, HttpGitHubClient
from infrastructure.connectors.github.issue_documents import (
    GitHubIssueConfig,
    GitHubIssueDocuments,
)
from infrastructure.connectors.github.repo_documents import GitHubRepoConfig, GitHubRepoDocuments

_MSG_REQUEST_FAILED = "The GitHub request failed."
_MSG_CONFIG = "GitHub connector configuration is invalid."


class GitHubConnectorConfigError(GitHubConfigError):
    """GitHub connector settings are missing or unusable."""


class GitHubKnowledgeConnector:
    """Merge repository and ProjectV2 issue GitHub adapters."""

    def __init__(
        self,
        settings: object | None = None,
        *,
        repo_documents: GitHubRepoDocuments | None = None,
        issue_documents: GitHubIssueDocuments | None = None,
        client: GitHubClient | None = None,
    ) -> None:
        if settings is not None:
            client = client or _client_from_settings(settings)
            if _setting_text(settings, "owner") and _setting_text(settings, "repo"):
                repo_documents = GitHubRepoDocuments(
                    client,
                    GitHubRepoConfig(
                        owner=_setting_text(settings, "owner") or "",
                        repo=_setting_text(settings, "repo") or "",
                        ref=_setting_text(settings, "ref") or "HEAD",
                        include_prefixes=tuple(getattr(settings, "include_paths", ())),
                        exclude_prefixes=tuple(getattr(settings, "exclude_paths", ())),
                        text_extensions=frozenset(getattr(settings, "extensions", ())),
                        max_size_bytes=int(getattr(settings, "max_file_bytes", 1_000_000)),
                    ),
                )
            project_owner = _setting_text(settings, "project_owner")
            project_number = getattr(settings, "project_number", None)
            if project_owner and isinstance(project_number, int):
                try:
                    project_node_id = client.resolve_project_v2_id(
                        project_owner, project_number
                    )
                except ConnectorError as error:
                    # Project settings are configuration for the Issues half.
                    # Map to ConfigError so Hub/CLI report configuration_error
                    # instead of a generic sync failure; leave repo_documents
                    # intact for callers that recover from ConfigurationError.
                    raise GitHubConnectorConfigError(_MSG_CONFIG) from error
                issue_documents = GitHubIssueDocuments(
                    client,
                    GitHubIssueConfig(
                        project_node_id=project_node_id,
                        include_comments=bool(
                            getattr(settings, "include_issue_comments", False)
                        ),
                    ),
                )
            if repo_documents is None and issue_documents is None:
                raise GitHubConnectorConfigError(_MSG_CONFIG)
        self._repo_documents = repo_documents
        self._issue_documents = issue_documents

    def list_documents(self) -> Sequence[ConnectorDocument]:
        documents: list[ConnectorDocument] = []
        if self._repo_documents is not None:
            documents.extend(self._repo_documents.list_documents())
        if self._issue_documents is not None:
            documents.extend(self._issue_documents.list_documents())
        return tuple(documents)

    def fetch_document(self, document: ConnectorDocument) -> SourceDocument:
        kind = document.extra.get("github_kind")
        if kind == "repo" or (kind is None and ":" in document.source_id and not document.source_id.startswith("issue:")):
            if self._repo_documents is None:
                raise ConnectorError(_MSG_REQUEST_FAILED)
            return self._repo_documents.fetch_document(document)
        if kind == "issue" or (kind is None and document.source_id.startswith("issue:")):
            if self._issue_documents is None:
                raise ConnectorError(_MSG_REQUEST_FAILED)
            return self._issue_documents.fetch_document(document)
        raise ConnectorError(_MSG_REQUEST_FAILED)


def _implements_port(connector: GitHubKnowledgeConnector) -> KnowledgeConnector:
    return connector


def _client_from_settings(settings: object) -> GitHubClient:
    token = _setting_text(settings, "token")
    if token is None:
        raise GitHubConnectorConfigError(_MSG_CONFIG)
    try:
        return HttpGitHubClient(
            token,
            page_size=int(getattr(settings, "page_size", 100)),
        )
    except GitHubConfigError as error:
        raise GitHubConnectorConfigError(str(error)) from error


def _setting_text(settings: object, name: str) -> str | None:
    value = getattr(settings, name, None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
