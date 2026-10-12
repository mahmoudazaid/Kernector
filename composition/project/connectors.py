"""Configured connectors and the scope kinds each one accepts.

Connection state changes at runtime (connect, first sync, disconnect), so the
stores are read on every lookup.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from domain.knowledge import SourceType
from domain.project.ports import SourceScopeResolver
from infrastructure.config import Settings
from infrastructure.connectors.github.oauth import GitHubOAuthConnectionStore
from infrastructure.connectors.jira.data_center_state import JiraDataCenterStateStore
from infrastructure.connectors.jira.oauth import JiraOAuthConnectionStore


def configured_connectors(settings: Settings) -> dict[str, str]:
    """Return ``connector_id`` to catalog ``source_type`` for configured connectors."""
    github = str(SourceType.GITHUB)
    jira = str(SourceType.JIRA)
    found: dict[str, str] = {}
    if settings.github.connector_id:
        found[settings.github.connector_id] = github
    github_oauth = GitHubOAuthConnectionStore(settings.github_oauth.token_path).load()
    if github_oauth is not None and github_oauth.connector_id:
        found[github_oauth.connector_id] = github
    data_center = settings.jira_data_center
    if data_center is None:
        jira_oauth = JiraOAuthConnectionStore(settings.jira_oauth.token_path).load()
        if jira_oauth is not None and jira_oauth.connector_id:
            found[jira_oauth.connector_id] = jira
    else:
        state = JiraDataCenterStateStore(data_center.state_path).load()
        if state is not None and state.connector_id:
            found[state.connector_id] = jira
    return found


@dataclass(frozen=True, slots=True)
class ConfiguredConnectorScopeKinds:
    """Implements ``domain.project.ports.ConnectorScopeKinds``."""

    settings: Settings
    resolvers: Mapping[str, SourceScopeResolver]

    def scope_kinds_for(self, connector_id: str) -> frozenset[str] | None:
        source_type = configured_connectors(self.settings).get(connector_id)
        resolver = None if source_type is None else self.resolvers.get(source_type)
        return None if resolver is None else resolver.scope_kinds
