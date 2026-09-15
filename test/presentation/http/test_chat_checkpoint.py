"""DELETE /api/v1/chat/threads/{id}/checkpoint — clear short-term agent memory."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from presentation.http.app import create_app
from presentation.http.deps import (
    get_clear_agent_thread,
    get_settings,
)


class _RecordingClear:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, *, conversation_id: str) -> None:
        self.calls.append(conversation_id)


def _client_with_clear(clear: _RecordingClear) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_clear_agent_thread] = lambda: clear
    return TestClient(app, raise_server_exceptions=False)


def test_clear_checkpoint_returns_204_twice() -> None:
    clear = _RecordingClear()
    client = _client_with_clear(clear)

    first = client.delete("/api/v1/chat/threads/conv-1/checkpoint")
    second = client.delete("/api/v1/chat/threads/conv-1/checkpoint")

    assert first.status_code == 204
    assert first.content == b""
    assert second.status_code == 204
    assert clear.calls == ["conv-1", "conv-1"]


def test_clear_checkpoint_rejects_malformed_conversation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SOFTWARE_DELIVERY_AGENT_LOOP", raising=False)
    get_settings.cache_clear()

    client = TestClient(create_app(), raise_server_exceptions=False)
    response = client.delete("/api/v1/chat/threads/bad:id/checkpoint")

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_clear_checkpoint_noop_when_agent_loop_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SOFTWARE_DELIVERY_AGENT_LOOP", raising=False)
    get_settings.cache_clear()

    client = TestClient(create_app(), raise_server_exceptions=False)
    response = client.delete("/api/v1/chat/threads/conv-1/checkpoint")
    assert response.status_code == 204
