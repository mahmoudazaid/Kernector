"""Jira KnowledgeConnector."""

from __future__ import annotations

from collections.abc import Sequence

from domain.knowledge import ConnectorDocument, SourceDocument
from domain.ports import KnowledgeConnector
from infrastructure.connectors.jira.client import JiraClient
from infrastructure.connectors.jira.issue_documents import (
    JiraIssueConfig,
    JiraIssueDocuments,
)


class JiraKnowledgeConnector:
    """Expose selected Jira project issues through the generic connector port."""

    def __init__(self, client: JiraClient, config: JiraIssueConfig) -> None:
        self._issues = JiraIssueDocuments(client, config)

    def list_documents(self) -> Sequence[ConnectorDocument]:
        return self._issues.list_documents()

    def fetch_document(self, document: ConnectorDocument) -> SourceDocument:
        return self._issues.fetch_document(document)


def _implements_port(connector: JiraKnowledgeConnector) -> KnowledgeConnector:
    return connector
