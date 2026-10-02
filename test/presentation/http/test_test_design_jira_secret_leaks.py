"""Jira DC secrets never leak from Test Design: document, HTTP, MCP, logs (#353)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from composition import container as composition_container
from composition.mcp.access import McpCallerContext
from composition.test_design.sources import TestDesignSourceRegistry
from domain.errors import ConnectorAuthError, ConnectorError, ConnectorNotFoundError
from domain.knowledge import SourceLocator
from infrastructure.config import load_settings
from infrastructure.connectors.jira.data_center import JiraDataCenterHttpDiagnostic
from infrastructure.connectors.jira.data_center_state import JiraDataCenterStateStore
from infrastructure.connectors.jira.errors import JiraRateLimitError
from presentation.http.app import create_app
from presentation.http.deps import get_test_design_facade
from test.composition.jira.jira_fakes import dc_settings
from test.composition.test_design.test_design_fakes import (
    build_fake_facade,
    settings_with_pack,
)

TOKEN = "SENTINEL-TOKEN-4c1d9e"
BASE_URL = "https://jira-sentinel-8b2f.example.com/ctx-sentinel"
PAYLOAD = "RAW-PAYLOAD-SENTINEL-51aa"
AC_FIELD = "customfield_10200"
SENTINELS = (TOKEN, BASE_URL, "jira-sentinel-8b2f", PAYLOAD)
START_TOOL = "software_delivery.test_design_start"


def _with_diagnostic(error: Exception) -> Exception:
    error.__cause__ = JiraDataCenterHttpDiagnostic(
        f"HTTP 4xx from {BASE_URL}: {PAYLOAD} Bearer {TOKEN}"
    )
    return error


class _LeakyClient:
    """Returns sentinel-laden payloads and raises errors carrying raw diagnostics."""

    def __init__(self) -> None:
        self.failure: Callable[[], Exception] | None = None
        self.key: str | None = None

    def get_issue(self, key: str, fields: Sequence[str]) -> Mapping[str, object]:
        if self.failure is not None:
            raise self.failure()
        return {
            "id": "10001",
            "key": self.key or key,
            "self": f"{BASE_URL}/rest/api/2/issue/10001",
            "fields": {
                "summary": "Login",
                "description": "Users log in with email.",
                "updated": "2026-09-14T12:00:00.000+0000",
                "environment": PAYLOAD,
                AC_FIELD: {"value": PAYLOAD, "self": BASE_URL},
            },
        }


_FAILURES: dict[str, Callable[[_LeakyClient], None]] = {
    "not-found": lambda c: setattr(
        c, "failure", lambda: _with_diagnostic(ConnectorNotFoundError("missing"))
    ),
    "rejected": lambda c: setattr(
        c, "failure", lambda: _with_diagnostic(ConnectorAuthError("rejected"))
    ),
    "rate-limited": lambda c: setattr(
        c, "failure", lambda: _with_diagnostic(JiraRateLimitError(30))
    ),
    "request-failed": lambda c: setattr(
        c, "failure", lambda: _with_diagnostic(ConnectorError(f"failed {PAYLOAD}"))
    ),
    "payload-mismatch": lambda c: setattr(c, "key", "OPS-9"),
}


@pytest.fixture
def client() -> _LeakyClient:
    return _LeakyClient()


@pytest.fixture
def registry(tmp_path: Path, client: _LeakyClient) -> TestDesignSourceRegistry:
    settings = dc_settings(load_settings(), tmp_path, base_url=BASE_URL, token=TOKEN)
    assert settings.jira_data_center is not None
    settings = replace(
        settings,
        jira_data_center=replace(
            settings.jira_data_center, acceptance_criteria_field=AC_FIELD
        ),
    )
    return composition_container.build_test_design_sources(
        settings,
        jira_dc_state_store=JiraDataCenterStateStore(tmp_path / "jira-dc-connection.json"),
        jira_dc_client_factory=lambda _base_url, _token: client,
    )


def _assert_clean(text: str) -> None:
    for sentinel in SENTINELS:
        assert sentinel not in text


def test_returned_source_document_carries_no_secrets(
    registry: TestDesignSourceRegistry,
) -> None:
    document = registry.resolve("jira").reader().fetch(SourceLocator("jira", "ENG-7"))

    _assert_clean(repr(document))
    _assert_clean(document.content)


def _http(tmp_path: Path, registry: TestDesignSourceRegistry) -> TestClient:
    facade = build_fake_facade(tmp_path, sources=registry)
    app = create_app(cors_origins=())
    app.dependency_overrides[get_test_design_facade] = lambda: facade
    return TestClient(app, raise_server_exceptions=False)


def _create(http: TestClient, locator: str = "ENG-7"):  # noqa: ANN202
    return http.post(
        "/api/v1/test-design/drafts",
        json={
            "conversation_id": "conv-leak",
            "source_locator": {"provider": "jira", "locator": locator},
        },
    )


def test_http_success_response_and_logs_carry_no_secrets(
    tmp_path: Path,
    registry: TestDesignSourceRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    response = _create(_http(tmp_path, registry))

    assert response.status_code == 200
    _assert_clean(response.text)
    _assert_clean(caplog.text)


@pytest.mark.parametrize("failure", sorted(_FAILURES))
def test_http_problem_responses_and_logs_carry_no_secrets(
    tmp_path: Path,
    registry: TestDesignSourceRegistry,
    client: _LeakyClient,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    _FAILURES[failure](client)

    response = _create(_http(tmp_path, registry))

    assert response.status_code >= 400
    assert response.json()["code"]
    _assert_clean(response.text)
    _assert_clean(caplog.text)


def _mcp_invoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry: TestDesignSourceRegistry,
):  # noqa: ANN202
    from application.retrieve_knowledge import RetrieveKnowledge
    from composition.mcp.wiring import build_mcp_tool_registry
    from test.composition.mcp.test_mcp_registry import _StubRetrieve

    settings = settings_with_pack(workspace_id="ws-a")
    monkeypatch.setattr(
        composition_container,
        "build_test_design_facade",
        lambda _active: build_fake_facade(tmp_path, sources=registry),
    )
    tools = build_mcp_tool_registry(
        settings, retrieve=cast(RetrieveKnowledge, _StubRetrieve())
    )
    caller = McpCallerContext("ws-a", "default", frozenset({START_TOOL}))
    return tools.invoke_authorized(caller, START_TOOL, {"issue_locator": "ENG-7"})


def test_mcp_success_payload_and_logs_carry_no_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry: TestDesignSourceRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    result = _mcp_invoke(tmp_path, monkeypatch, registry)

    assert result.is_error is False
    assert json.loads(result.text)["ticket_identifier"] == "ENG-7"
    _assert_clean(result.text)
    _assert_clean(caplog.text)


@pytest.mark.parametrize("failure", sorted(_FAILURES))
def test_mcp_error_payloads_and_logs_carry_no_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry: TestDesignSourceRegistry,
    client: _LeakyClient,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    _FAILURES[failure](client)

    result = _mcp_invoke(tmp_path, monkeypatch, registry)

    assert result.is_error is True
    _assert_clean(result.text)
    _assert_clean(json.dumps(dict(result.structured or {})))
    _assert_clean(caplog.text)
