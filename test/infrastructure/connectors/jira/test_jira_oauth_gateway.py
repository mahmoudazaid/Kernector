"""Atlassian OAuth 2.0 (3LO) gateway and stores — httpx.MockTransport, no live calls."""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from domain.errors import ConnectorAuthError
from infrastructure.config import JiraOAuthSettings
from infrastructure.connectors.jira.oauth import (
    AccessibleResource,
    HttpJiraOAuthGateway,
    JiraOAuthConnection,
    JiraOAuthConnectionStore,
    JiraOAuthStateStore,
    JiraSite,
    eligible_jira_sites,
    JiraOAuthGrant,
    JiraOAuthInvalidGrantError,
    JiraOAuthTransportError,
    authorization_url,
)

SECRET_ACCESS = "atl-access-secret"
SECRET_REFRESH = "atl-refresh-secret"
CLIENT_SECRET = "client-secret-value"


def _settings(tmp_path: Path) -> JiraOAuthSettings:
    return JiraOAuthSettings(
        client_id="client-id",
        client_secret=CLIENT_SECRET,
        redirect_uri="http://localhost:8000/api/v1/connectors/jira/oauth/callback",
        frontend_redirect="http://localhost:3000/documents",
        token_path=tmp_path / "jira-oauth-connection.json",
        state_path=tmp_path / "jira-oauth-state.json",
    )


def test_authorization_url_follows_atlassian_3lo_contract(tmp_path: Path) -> None:
    url = authorization_url(_settings(tmp_path), state="state-123")

    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://auth.atlassian.com/authorize"
    assert parse_qs(parts.query) == {
        "audience": ["api.atlassian.com"],
        "client_id": ["client-id"],
        "scope": ["read:jira-work read:me offline_access"],
        "redirect_uri": ["http://localhost:8000/api/v1/connectors/jira/oauth/callback"],
        "state": ["state-123"],
        "response_type": ["code"],
        "prompt": ["consent"],
    }
    assert CLIENT_SECRET not in url


def _gateway(tmp_path: Path, handler) -> HttpJiraOAuthGateway:
    return HttpJiraOAuthGateway(_settings(tmp_path), transport=httpx.MockTransport(handler))


def test_exchange_code_posts_json_and_returns_grant(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": SECRET_ACCESS,
                "refresh_token": SECRET_REFRESH,
                "expires_in": 3600,
                "scope": "read:jira-work read:me offline_access",
            },
        )

    grant = _gateway(tmp_path, handler).exchange_code("auth-code")

    [request] = seen
    assert str(request.url) == "https://auth.atlassian.com/oauth/token"
    assert json.loads(request.content) == {
        "grant_type": "authorization_code",
        "client_id": "client-id",
        "client_secret": CLIENT_SECRET,
        "code": "auth-code",
        "redirect_uri": "http://localhost:8000/api/v1/connectors/jira/oauth/callback",
    }
    assert grant == JiraOAuthGrant(
        access_token=SECRET_ACCESS, refresh_token=SECRET_REFRESH, expires_in=3600
    )
    assert SECRET_ACCESS not in repr(grant)
    assert SECRET_REFRESH not in repr(grant)


def test_refresh_returns_rotated_refresh_token(tmp_path: Path) -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"access_token": "new-access", "refresh_token": "rotated-refresh", "expires_in": 3600},
        )

    grant = _gateway(tmp_path, handler).refresh(SECRET_REFRESH)

    assert bodies == [
        {
            "grant_type": "refresh_token",
            "client_id": "client-id",
            "client_secret": CLIENT_SECRET,
            "refresh_token": SECRET_REFRESH,
        }
    ]
    assert grant.access_token == "new-access"
    assert grant.refresh_token == "rotated-refresh"


def test_refresh_without_returned_refresh_token_reports_none(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "new-access", "expires_in": 3600})

    grant = _gateway(tmp_path, handler).refresh(SECRET_REFRESH)

    assert grant.refresh_token is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, json={"error": "invalid_grant", "error_description": "Unknown or invalid refresh token."}),
        httpx.Response(400, json={"error": "invalid_grant"}),
        httpx.Response(401, json={"error": "unauthorized_client"}),
    ],
)
def test_refresh_rejection_raises_invalid_grant_without_tokens(
    tmp_path: Path, response: httpx.Response
) -> None:
    with pytest.raises(JiraOAuthInvalidGrantError) as caught:
        _gateway(tmp_path, lambda request: response).refresh(SECRET_REFRESH)

    assert SECRET_REFRESH not in str(caught.value)
    assert CLIENT_SECRET not in str(caught.value)


JIRA_SCOPES = ["read:jira-work", "read:me"]
CONFLUENCE_SCOPES = ["read:confluence-content.all"]


def test_fetch_accessible_resources_parses_containers(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "id": "cloud-1",
                    "name": "Acme",
                    "url": "https://acme.atlassian.net",
                    "scopes": JIRA_SCOPES,
                    "avatarUrl": "https://x/avatar.png",
                }
            ],
        )

    resources = _gateway(tmp_path, handler).fetch_accessible_resources(SECRET_ACCESS)

    [request] = seen
    assert str(request.url) == "https://api.atlassian.com/oauth/token/accessible-resources"
    assert request.headers["Authorization"] == f"Bearer {SECRET_ACCESS}"
    assert resources == (
        AccessibleResource(
            id="cloud-1",
            name="Acme",
            url="https://acme.atlassian.net",
            scopes=("read:jira-work", "read:me"),
        ),
    )


def test_fetch_accessible_resources_auth_failure_is_typed(tmp_path: Path) -> None:
    with pytest.raises(ConnectorAuthError):
        _gateway(tmp_path, lambda request: httpx.Response(401)).fetch_accessible_resources(
            SECRET_ACCESS
        )


def test_fetch_accessible_resources_malformed_payload_is_transport_error(tmp_path: Path) -> None:
    with pytest.raises(JiraOAuthTransportError):
        _gateway(
            tmp_path, lambda request: httpx.Response(200, json={"not": "a list"})
        ).fetch_accessible_resources(SECRET_ACCESS)


def _resource(rid: str, name: str, url: str, scopes: list[str]) -> AccessibleResource:
    return AccessibleResource(id=rid, name=name, url=url, scopes=tuple(scopes))


def test_eligible_sites_zero_when_no_resources_or_confluence_only() -> None:
    assert eligible_jira_sites(()) == ()
    assert (
        eligible_jira_sites(
            (_resource("c1", "Wiki", "https://acme.atlassian.net", CONFLUENCE_SCOPES),)
        )
        == ()
    )


def test_eligible_sites_one_jira_site_with_normalized_url() -> None:
    sites = eligible_jira_sites(
        (_resource("c1", "Acme", "https://ACME.atlassian.net/", JIRA_SCOPES),)
    )

    assert sites == (
        JiraSite(cloud_id="c1", site_url="https://acme.atlassian.net", name="Acme"),
    )


def test_eligible_sites_many_sorted_by_name_and_confluence_duplicate_ignored() -> None:
    sites = eligible_jira_sites(
        (
            _resource("c2", "Zeta", "https://zeta.atlassian.net", JIRA_SCOPES),
            _resource("c1", "Acme Wiki", "https://acme.atlassian.net", CONFLUENCE_SCOPES),
            _resource("c1", "Acme", "https://acme.atlassian.net", JIRA_SCOPES),
            _resource("c3", "beta", "https://beta.atlassian.net", JIRA_SCOPES),
        )
    )

    assert [(site.cloud_id, site.name) for site in sites] == [
        ("c1", "Acme"),
        ("c3", "beta"),
        ("c2", "Zeta"),
    ]


def test_eligible_sites_skip_non_https_urls() -> None:
    assert (
        eligible_jira_sites((_resource("c1", "Acme", "javascript:alert(1)", JIRA_SCOPES),))
        == ()
    )


def test_fetch_account_name_reads_me_endpoint(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"account_id": "a1", "name": "Mia Krystof"})

    name = _gateway(tmp_path, handler).fetch_account_name(SECRET_ACCESS)

    assert str(seen[0].url) == "https://api.atlassian.com/me"
    assert name == "Mia Krystof"


def test_fetch_account_name_failure_omits_label(tmp_path: Path) -> None:
    assert _gateway(tmp_path, lambda request: httpx.Response(500)).fetch_account_name(
        SECRET_ACCESS
    ) is None


SITE = JiraSite(cloud_id="c1", site_url="https://acme.atlassian.net", name="Acme")


def _connection(**overrides: object) -> JiraOAuthConnection:
    base = JiraOAuthConnection(
        access_token=SECRET_ACCESS,
        refresh_token=SECRET_REFRESH,
        access_token_expires_at=1_900_000_000.0,
        account_name="Mia",
        site=SITE,
        project_keys=("KAN", "OPS"),
        connector_id="conn-1",
    )
    return dataclasses.replace(base, **overrides)


def test_connection_store_round_trips_site_and_writes_0600(tmp_path: Path) -> None:
    path = tmp_path / "jira-oauth-connection.json"
    store = JiraOAuthConnectionStore(path)

    store.save(_connection(last_sync_new=3, last_synced_at="2026-09-27T10:00:00+00:00"))

    loaded = store.load()
    assert loaded == _connection(last_sync_new=3, last_synced_at="2026-09-27T10:00:00+00:00")
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert SECRET_ACCESS not in repr(loaded)
    assert SECRET_REFRESH not in repr(loaded)


def test_connection_store_keeps_reauth_record_without_tokens(tmp_path: Path) -> None:
    store = JiraOAuthConnectionStore(tmp_path / "jira-oauth-connection.json")

    store.save(
        _connection(access_token=None, refresh_token=None, reauthorization_required=True)
    )

    loaded = store.load()
    assert loaded is not None
    assert loaded.reauthorization_required is True
    assert loaded.access_token is None and loaded.refresh_token is None
    assert loaded.site == SITE
    assert SECRET_REFRESH not in (tmp_path / "jira-oauth-connection.json").read_text()


def test_connection_store_mutate_applies_to_current_value_and_clear(tmp_path: Path) -> None:
    store = JiraOAuthConnectionStore(tmp_path / "jira-oauth-connection.json")
    store.save(_connection())

    updated = store.mutate(
        lambda current: dataclasses.replace(current, refresh_token="rotated")
        if current
        else None
    )
    unchanged = store.mutate(lambda current: None)

    assert updated is not None and updated.refresh_token == "rotated"
    assert unchanged == updated
    assert store.load() == updated
    store.clear()
    assert store.load() is None


def test_state_is_single_use_and_expires(tmp_path: Path) -> None:
    store = JiraOAuthStateStore(tmp_path / "jira-oauth-state.json", ttl_seconds=600)
    state = store.issue()

    assert store.consume(state) is True
    assert store.consume(state) is False
    assert store.consume(None) is False

    expired = JiraOAuthStateStore(tmp_path / "jira-oauth-state-2.json", ttl_seconds=-1)
    assert expired.consume(expired.issue()) is False


@pytest.mark.parametrize("failure", ["server", "network"])
def test_refresh_transport_failure_raises_transport_error(tmp_path: Path, failure: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "network":
            raise httpx.ConnectError(f"cannot reach {SECRET_REFRESH}")
        return httpx.Response(503, text="unavailable")

    with pytest.raises(JiraOAuthTransportError) as caught:
        _gateway(tmp_path, handler).refresh(SECRET_REFRESH)

    assert not isinstance(caught.value, JiraOAuthInvalidGrantError)
    assert SECRET_REFRESH not in str(caught.value)
    assert caught.value.__cause__ is None
