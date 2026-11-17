"""Tests for HttpGitHubClient.get_issue and HTTP error taxonomy."""

from __future__ import annotations

import os

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
_ISSUE_OK = {
    "node_id": "I_kwDOExample",
    "number": 293,
    "title": "Live fetch",
    "body": "Acceptance criteria",
    "html_url": "https://github.com/mahmoudazaid/Kernector/issues/293",
    "updated_at": "2026-09-14T12:00:00Z",
    "repository_url": "https://api.github.com/repos/mahmoudazaid/Kernector",
}


def test_get_issue_returns_rest_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/mahmoudazaid/Kernector/issues/293"
        return httpx.Response(200, json=_ISSUE_OK)

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    payload = client.get_issue("mahmoudazaid", "Kernector", 293)
    assert payload["number"] == 293
    assert payload["node_id"] == "I_kwDOExample"


@pytest.mark.parametrize("token", [None, "", "   "])
def test_get_issue_omits_authorization_without_usable_token(token: str | None) -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, json=_ISSUE_OK)

    client = HttpGitHubClient(
        token,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    client.get_issue("mahmoudazaid", "Kernector", 293)
    assert "authorization" not in seen[0]


def test_get_issue_sends_bearer_for_valid_token() -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, json=_ISSUE_OK)

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    client.get_issue("mahmoudazaid", "Kernector", 293)
    assert seen[0].get("authorization") == f"Bearer {SECRET}"


def test_anonymous_client_does_not_use_env_pat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_ENV_PAT_MUST_NOT_APPEAR")
    monkeypatch.setenv("GITHUB_PAT", "ghp_ENV_PAT_MUST_NOT_APPEAR")
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, json=_ISSUE_OK)

    client = HttpGitHubClient(
        None,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    client.get_issue("mahmoudazaid", "Kernector", 293)
    assert "authorization" not in seen[0]
    assert os.environ.get("GITHUB_TOKEN") == "ghp_ENV_PAT_MUST_NOT_APPEAR"


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


def test_permission_403_is_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"message": "Resource not accessible by integration"},
            headers={"x-ratelimit-remaining": "42"},
        )

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ConnectorAuthError):
        client.get_issue("o", "r", 1)


@pytest.mark.parametrize(
    "headers",
    [
        {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"},
        {"retry-after": "60"},
    ],
)
def test_rate_limit_403_from_headers(headers: dict[str, str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers=headers,
        )

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ConnectorRateLimitError):
        client.get_issue("o", "r", 1)


def test_secondary_rate_limit_403_from_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "message": (
                    "You have exceeded a secondary rate limit."
                    " Please wait a few minutes before you try again."
                )
            },
            headers={"x-ratelimit-remaining": "50"},
        )

    client = HttpGitHubClient(
        SECRET,
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ConnectorRateLimitError):
        client.get_issue("o", "r", 1)


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
