"""Associations accept only configured connectors and their scope kinds (#372)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from composition.project.connectors import (
    ConfiguredConnectorScopeKinds,
    configured_connectors,
)
from composition.project.container import build_scope_resolvers
from infrastructure.config import JiraDataCenterSettings, Settings, load_settings
from infrastructure.connectors.github.oauth import (
    GitHubOAuthConnection,
    GitHubOAuthConnectionStore,
)
from infrastructure.connectors.jira.data_center_state import (
    JiraDataCenterState,
    JiraDataCenterStateStore,
)
from infrastructure.connectors.jira.oauth import (
    JiraOAuthConnection,
    JiraOAuthConnectionStore,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    base = load_settings()
    return replace(
        base,
        github=replace(base.github, connector_id=None),
        github_oauth=replace(
            base.github_oauth, token_path=tmp_path / "github-oauth-connection.json"
        ),
        jira_oauth=replace(
            base.jira_oauth, token_path=tmp_path / "jira-oauth-connection.json"
        ),
        jira_data_center=None,
    )


def _github_oauth(settings: Settings, connector_id: str | None) -> None:
    GitHubOAuthConnectionStore(settings.github_oauth.token_path).save(
        GitHubOAuthConnection(
            access_token="token",
            refresh_token=None,
            account_login="octo",
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
            connector_id=connector_id,
        )
    )


def _jira_oauth(settings: Settings, connector_id: str) -> None:
    JiraOAuthConnectionStore(settings.jira_oauth.token_path).save(
        JiraOAuthConnection("token", None, connector_id=connector_id)
    )


def test_nothing_connected_means_no_configured_connectors(
    settings: Settings,
) -> None:
    assert configured_connectors(settings) == {}


def test_connector_ids_come_from_env_and_connection_stores(
    settings: Settings,
) -> None:
    with_env = replace(settings, github=replace(settings.github, connector_id="gh-env"))
    _github_oauth(settings, "gh-oauth")
    _jira_oauth(settings, "jira-cloud")

    assert configured_connectors(with_env) == {
        "gh-env": "github",
        "gh-oauth": "github",
        "jira-cloud": "jira",
    }


def test_github_grant_without_a_connector_id_is_not_configured(
    settings: Settings,
) -> None:
    _github_oauth(settings, None)

    assert configured_connectors(settings) == {}


def test_data_center_mode_uses_its_state_instead_of_the_cloud_grant(
    settings: Settings, tmp_path: Path
) -> None:
    _jira_oauth(settings, "jira-cloud")
    state_path = tmp_path / "jira-dc-connection.json"
    JiraDataCenterStateStore(state_path).mutate(
        lambda _current: JiraDataCenterState(connector_id="jira-dc")
    )
    data_center = replace(
        settings,
        jira_data_center=JiraDataCenterSettings(
            base_url="https://jira.example.com", token="pat", state_path=state_path
        ),
    )

    assert configured_connectors(data_center) == {"jira-dc": "jira"}


def test_scope_kinds_are_keyed_by_the_connector_type(settings: Settings) -> None:
    _github_oauth(settings, "gh-1")
    _jira_oauth(settings, "jira-1")
    connectors = ConfiguredConnectorScopeKinds(settings, build_scope_resolvers())

    assert connectors.scope_kinds_for("gh-1") == frozenset({"repo"})
    assert connectors.scope_kinds_for("jira-1") == frozenset({"project_key"})
    assert connectors.scope_kinds_for("no-such-connector") is None
