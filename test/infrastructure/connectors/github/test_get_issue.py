"""Tests for HttpGitHubClient.get_issue and HTTP error taxonomy."""

from __future__ import annotations

import httpx
import pytest

from domain.errors import (
    ConnectorAuthError,
    ConnectorNetworkError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    ConnectorUnavailableError,
)
from infrastructure.connectors.github.client import HttpGitHubClient

SECRET = "ghp_SECRET_SHOULD_NOT_LEAK"


def test_get_issue_returns_rest_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/mahmoudazaid/Kernector/issues/293"
        return httpx.Response(
            200,
            json={
                "node_id": "I_kwDOExample",
                "number": 293,
                "title": "Live fetch",
                "body": "Acceptance criteria",
                "html_url": "https://github.com/mahmoudazaid/Kernector/issues/293",
                "updated_at": "2026-09-14T12:00:00Z",
                "repository_url": "https://api.github.com/repos/mahmoudazaid/Kernector",
            },
        )

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    payload = client.get_issue("mahmoudazaid", "Kernector", 293)
    assert payload["number"] == 293
    assert payload["node_id"] == "I_kwDOExample"


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, ConnectorAuthError),
        (403, ConnectorAuthError),
        (404, ConnectorNotFoundError),
        (429, ConnectorRateLimitError),
        (503, ConnectorUnavailableError),
    ],
)
def test_get_issue_maps_http_status(status: int, error_type: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": SECRET})

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(error_type) as raised:
        client.get_issue("o", "r", 1)
    assert SECRET not in str(raised.value)


def test_get_issue_maps_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ConnectorTimeoutError):
        client.get_issue("o", "r", 1)


def test_get_issue_maps_transport_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ConnectorNetworkError):
        client.get_issue("o", "r", 1)
