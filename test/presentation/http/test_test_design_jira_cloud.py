"""Jira Cloud Test Design over HTTP, MCP, and exception chains (#423)."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from composition import container as composition_container
from composition.mcp.access import McpCallerContext
from composition.test_design.sources import TestDesignSourceRegistry
from application.errors import SourceReauthorizationRequiredError
from domain.errors import ConnectorAuthError, ConnectorError, ConnectorNotFoundError
from domain.knowledge import SourceLocator
from infrastructure.config import DomainToolSettings, load_settings
from infrastructure.connectors.jira.oauth import JiraOAuthError
from presentation.http.app import create_app
from presentation.http.deps import get_settings, get_test_design_facade
from test.composition.jira.jira_fakes import (
    ACME,
    FakeGateway,
    connection,
    jira_settings,
    stores,
)
from test.composition.test_design.test_design_fakes import (
    build_fake_facade,
    settings_with_pack,
)

ACCESS = "SENTINEL-ACCESS-4c1d9e"
REFRESH = "SENTINEL-REFRESH-91aa"
CLOUD_ID = "cloud-sentinel-id"
SITE = "https://site-sentinel.example"
PAYLOAD = "RAW-PAYLOAD-SENTINEL-51aa"
SENTINELS = (ACCESS, REFRESH, CLOUD_ID, SITE, PAYLOAD)
START_TOOL = "software_delivery.test_design_start"


def _assert_clean(text: str) -> None:
    for sentinel in SENTINELS:
        assert sentinel not in text


def _assert_chain_clean(error: BaseException) -> None:
    _assert_clean(str(error))
    seen: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in seen:
        seen.append(current)
        _assert_clean(str(current))
        _assert_clean(repr(current))
        nxt = current.__cause__ or current.__context__
        current = nxt if isinstance(nxt, BaseException) else None
    assert error.__cause__ is None
    assert error.__context__ is None


class _LeakyClient:
    def __init__(self) -> None:
        self.failure: Exception | None = None
        self.key: str | None = None

    def get_issue(self, key: str, fields: Sequence[str]) -> Mapping[str, object]:
        del fields
        if self.failure is not None:
            raise self.failure
        return {
            "id": "10001",
            "key": self.key or key,
            "self": f"{SITE}/rest/api/3/issue/10001",
            "fields": {
                "summary": "Login",
                "description": "Users log in with email.",
                "updated": "2026-09-14T12:00:00.000+0000",
                "environment": PAYLOAD,
                "customfield_10200": {"value": PAYLOAD, "self": f"{SITE}/{CLOUD_ID}"},
            },
        }


def _registry(
    tmp_path: Path,
    client: _LeakyClient,
    *,
    connected: bool = True,
    reauth: bool = False,
    gateway: FakeGateway | None = None,
) -> TestDesignSourceRegistry:
    settings = replace(
        jira_settings(load_settings(), tmp_path, acceptance_criteria_field="customfield_10200"),
        jira_data_center=None,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    _states, tokens = stores(settings)
    if connected:
        tokens.save(
            connection(
                access_token=ACCESS,
                refresh_token=REFRESH,
                site=replace(ACME, cloud_id=CLOUD_ID, site_url=SITE),
                project_keys=("FD",),
                reauthorization_required=reauth,
                access_token_expires_at=0.0 if gateway is not None else None,
            )
        )
    return composition_container.build_test_design_sources(
        settings,
        jira_cloud_connection_store=tokens,
        jira_cloud_gateway=gateway or FakeGateway(),
        jira_cloud_client_factory=lambda _token, _cloud_id: client,
    )


def _http(tmp_path: Path, registry: TestDesignSourceRegistry) -> TestClient:
    facade = build_fake_facade(tmp_path, sources=registry)
    app = create_app(cors_origins=())
    app.dependency_overrides[get_test_design_facade] = lambda: facade
    return TestClient(app, raise_server_exceptions=False)


def _create(http: TestClient, locator: str = "FD-2"):
    return http.post(
        "/api/v1/test-design/drafts",
        json={
            "conversation_id": "conv-cloud",
            "source_locator": {"provider": "jira", "locator": locator},
        },
    )


def test_http_create_from_jira_cloud_issue(tmp_path: Path) -> None:
    response = _create(_http(tmp_path, _registry(tmp_path, _LeakyClient())))

    assert response.status_code == 200
    assert response.json()["ticket_identifier"] == "FD-2"
    _assert_clean(response.text)


def test_http_create_disconnected_is_source_not_connected(tmp_path: Path) -> None:
    response = _create(
        _http(tmp_path, _registry(tmp_path, _LeakyClient(), connected=False))
    )

    assert response.status_code == 409
    assert response.json()["code"] == "source_not_connected"
    assert response.json()["detail"] == "The source is not connected."


def test_http_create_reauth_is_source_reauthorization_required(tmp_path: Path) -> None:
    response = _create(
        _http(tmp_path, _registry(tmp_path, _LeakyClient(), reauth=True))
    )

    assert response.status_code == 409
    assert response.json()["code"] == "source_reauthorization_required"
    assert response.json()["detail"] == (
        "The source authorization was rejected. Connect again."
    )


def test_returned_source_document_carries_no_secrets(tmp_path: Path) -> None:
    document = (
        _registry(tmp_path, _LeakyClient()).resolve("jira").reader().fetch(
            SourceLocator("jira", "FD-2")
        )
    )

    _assert_clean(repr(document))
    _assert_clean(document.content)


def test_refresh_and_payload_failures_drop_the_diagnostic_chain(tmp_path: Path) -> None:
    client = _LeakyClient()
    diagnostic = ConnectorError(f"failed {PAYLOAD} {SITE} {CLOUD_ID}")
    diagnostic.__cause__ = RuntimeError(f"Bearer {ACCESS} refresh {REFRESH}")
    client.failure = diagnostic
    source = _registry(tmp_path, client).resolve("jira")

    with pytest.raises(ConnectorError) as caught:
        source.reader().fetch(SourceLocator("jira", "FD-2"))

    _assert_chain_clean(caught.value)

    gateway = FakeGateway(
        refresh_results=[JiraOAuthError(f"down {ACCESS} {CLOUD_ID} {SITE}")]
    )
    refreshing = _registry(tmp_path, _LeakyClient(), gateway=gateway).resolve("jira")
    with pytest.raises(ConnectorError) as refresh_caught:
        refreshing.reader().fetch(SourceLocator("jira", "FD-2"))

    _assert_chain_clean(refresh_caught.value)

    rejected = _LeakyClient()
    rejected.failure = ConnectorAuthError(f"rejected {ACCESS} {REFRESH} {CLOUD_ID}")
    reauth = _registry(tmp_path, rejected).resolve("jira")
    with pytest.raises(SourceReauthorizationRequiredError) as auth_caught:
        reauth.reader().fetch(SourceLocator("jira", "FD-2"))

    _assert_chain_clean(auth_caught.value)


def test_http_problem_and_logs_carry_no_secrets(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _LeakyClient()
    client.failure = ConnectorNotFoundError(f"missing {PAYLOAD} {ACCESS} {SITE}")
    response = _create(_http(tmp_path, _registry(tmp_path, client)))

    assert response.status_code >= 400
    _assert_clean(response.text)
    _assert_clean(caplog.text)


def _mcp_invoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry: TestDesignSourceRegistry):
    from application.retrieve_knowledge import RetrieveKnowledge
    from composition.mcp.wiring import build_mcp_tool_registry
    from test.composition.mcp.test_mcp_registry import _StubRetrieve

    settings = settings_with_pack(workspace_id="ws-a")
    monkeypatch.setattr(
        composition_container,
        "build_test_design_facade",
        lambda _active: build_fake_facade(tmp_path, sources=registry),
    )
    monkeypatch.setattr(
        composition_container, "build_test_design_sources", lambda _active: registry
    )
    tools = build_mcp_tool_registry(
        settings, retrieve=cast(RetrieveKnowledge, _StubRetrieve())
    )
    caller = McpCallerContext("ws-a", "default", frozenset({START_TOOL}))
    return tools.invoke_authorized(
        caller, START_TOOL, {"provider": "jira", "locator": "FD-2"}
    )


def test_mcp_success_and_error_payloads_carry_no_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    ok_registry = _registry(tmp_path, _LeakyClient())
    client = _LeakyClient()
    client.failure = ConnectorNotFoundError(f"missing {PAYLOAD} {ACCESS} {SITE} {CLOUD_ID}")
    bad_registry = _registry(tmp_path, client)
    success = _mcp_invoke(tmp_path, monkeypatch, ok_registry)
    assert success.is_error is False
    _assert_clean(success.text)
    _assert_clean(json.dumps(dict(success.structured or {})))

    failure = _mcp_invoke(tmp_path, monkeypatch, bad_registry)
    assert failure.is_error is True
    _assert_clean(failure.text)
    _assert_clean(json.dumps(dict(failure.structured or {})))
    _assert_clean(caplog.text)
