"""Rotating Atlassian refresh tokens: atomic persistence, reauth, no leakage."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from application.errors import JiraNotConnectedError, JiraReauthorizationRequiredError
from composition import JiraConnectorError, list_jira_sites
from infrastructure.config import load_settings
from infrastructure.connectors.jira.oauth import (
    JiraOAuthGrant,
    JiraOAuthInvalidGrantError,
    JiraOAuthTransportError,
)
from test.composition.jira.jira_fakes import (
    ACME,
    BETA,
    SECRET,
    FakeGateway,
    connection,
    jira_settings,
    resource,
    stores,
)


@pytest.fixture
def settings(tmp_path: Path):
    return jira_settings(load_settings(), tmp_path)


def _setup(settings, **overrides):
    _, tokens = stores(settings)
    tokens.save(connection(**overrides))
    return tokens


def test_list_sites_uses_stored_token(settings) -> None:
    tokens = _setup(settings)
    gateway = FakeGateway(resources=[resource(BETA), resource(ACME)])

    sites = list_jira_sites(settings, connection_store=tokens, gateway=gateway)

    assert [site.cloud_id for site in sites] == ["cloud-acme", "cloud-beta"]
    assert gateway.fetch_tokens == [f"{SECRET}-access-0"]
    assert gateway.refresh_calls == []


def test_list_sites_requires_connection(settings) -> None:
    _, tokens = stores(settings)

    with pytest.raises(JiraNotConnectedError):
        list_jira_sites(settings, connection_store=tokens, gateway=FakeGateway())


def test_list_sites_while_reauth_required(settings) -> None:
    tokens = _setup(settings, access_token=None, refresh_token=None, reauthorization_required=True)

    with pytest.raises(JiraReauthorizationRequiredError):
        list_jira_sites(settings, connection_store=tokens, gateway=FakeGateway())


def test_expired_access_token_is_refreshed_and_rotated_before_use(settings) -> None:
    tokens = _setup(settings, access_token_expires_at=0.0)
    gateway = FakeGateway()

    list_jira_sites(settings, connection_store=tokens, gateway=gateway)

    assert gateway.refresh_calls == [f"{SECRET}-refresh-0"]
    assert gateway.fetch_tokens == [f"{SECRET}-access-1"]
    stored = tokens.load()
    assert stored is not None
    assert stored.access_token == f"{SECRET}-access-1"
    assert stored.refresh_token == f"{SECRET}-refresh-1"
    assert stored.access_token_expires_at is not None
    assert stored.access_token_expires_at > 1_000_000_000


def test_rejected_access_token_refreshes_once_and_retries(settings) -> None:
    tokens = _setup(settings)
    gateway = FakeGateway(rejected_tokens={f"{SECRET}-access-0"})

    list_jira_sites(settings, connection_store=tokens, gateway=gateway)

    assert gateway.refresh_calls == [f"{SECRET}-refresh-0"]
    assert gateway.fetch_tokens == [f"{SECRET}-access-0", f"{SECRET}-access-1"]
    stored = tokens.load()
    assert stored is not None
    assert (stored.access_token, stored.refresh_token) == (
        f"{SECRET}-access-1",
        f"{SECRET}-refresh-1",
    )


def test_rotated_tokens_are_persisted_before_the_retry(settings) -> None:
    tokens = _setup(settings)
    seen: list[str | None] = []

    def _on_fetch(token: str) -> None:
        stored = tokens.load()
        seen.append(None if stored is None else stored.refresh_token)

    gateway = FakeGateway(rejected_tokens={f"{SECRET}-access-0"}, on_fetch=_on_fetch)

    list_jira_sites(settings, connection_store=tokens, gateway=gateway)

    assert seen == [f"{SECRET}-refresh-0", f"{SECRET}-refresh-1"]


def test_invalid_refresh_token_requires_reauth_without_leaking(
    settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    tokens = _setup(settings, access_token_expires_at=0.0)
    gateway = FakeGateway(refresh_results=[JiraOAuthInvalidGrantError("rejected")])

    with pytest.raises(JiraReauthorizationRequiredError) as raised:
        list_jira_sites(settings, connection_store=tokens, gateway=gateway)

    stored = tokens.load()
    assert stored is not None
    assert stored.reauthorization_required is True
    assert stored.access_token is None
    assert stored.refresh_token is None
    assert stored.site == ACME
    assert stored.connector_id == "conn-1"
    assert SECRET not in str(raised.value)
    assert SECRET not in caplog.text
    assert SECRET not in Path(settings.jira_oauth.token_path).read_text()


def test_refresh_without_rotated_token_requires_reauth(settings) -> None:
    tokens = _setup(settings, access_token_expires_at=0.0)
    gateway = FakeGateway(
        refresh_results=[JiraOAuthGrant(access_token=f"{SECRET}-access-1", refresh_token=None)]
    )

    with pytest.raises(JiraReauthorizationRequiredError):
        list_jira_sites(settings, connection_store=tokens, gateway=gateway)

    stored = tokens.load()
    assert stored is not None
    assert stored.refresh_token is None
    assert stored.access_token is None
    assert stored.reauthorization_required is True


def test_refresh_transport_failure_keeps_tokens(settings) -> None:
    tokens = _setup(settings, access_token_expires_at=0.0)
    gateway = FakeGateway(refresh_results=[JiraOAuthTransportError("down")])

    with pytest.raises(JiraConnectorError):
        list_jira_sites(settings, connection_store=tokens, gateway=gateway)

    stored = tokens.load()
    assert stored is not None
    assert stored.refresh_token == f"{SECRET}-refresh-0"
    assert stored.reauthorization_required is False


def test_retry_still_rejected_requires_reauth(settings) -> None:
    tokens = _setup(settings)
    gateway = FakeGateway(rejected_tokens={f"{SECRET}-access-0", f"{SECRET}-access-1"})

    with pytest.raises(JiraReauthorizationRequiredError):
        list_jira_sites(settings, connection_store=tokens, gateway=gateway)

    stored = tokens.load()
    assert stored is not None
    assert stored.reauthorization_required is True
    assert stored.refresh_token is None


def test_lost_refresh_race_uses_the_winner_tokens(settings) -> None:
    tokens = _setup(settings)

    def _concurrent_rotation(token: str) -> None:
        if token == f"{SECRET}-access-0":
            tokens.save(
                connection(
                    access_token=f"{SECRET}-access-9", refresh_token=f"{SECRET}-refresh-9"
                )
            )

    gateway = FakeGateway(
        rejected_tokens={f"{SECRET}-access-0"}, on_fetch=_concurrent_rotation
    )

    list_jira_sites(settings, connection_store=tokens, gateway=gateway)

    assert gateway.refresh_calls == []
    assert gateway.fetch_tokens[-1] == f"{SECRET}-access-9"
    stored = tokens.load()
    assert stored is not None
    assert stored.refresh_token == f"{SECRET}-refresh-9"
