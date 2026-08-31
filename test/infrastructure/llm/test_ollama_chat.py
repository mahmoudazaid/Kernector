"""Ollama chat adapter, tested through an injected HTTP post callable."""

from collections.abc import Mapping
from typing import Any

import pytest
import requests

from domain.errors import ProviderError
from domain.models import Message, Usage
from infrastructure.config import OllamaSettings
from infrastructure.llm.ollama import OllamaChat, OllamaConfigError


def _settings(**overrides: object) -> OllamaSettings:
    values: dict[str, object] = {
        "base_url": "http://localhost:11434",
        "model": "llama3.2",
        "timeout": 30.0,
    }
    values.update(overrides)
    return OllamaSettings(**values)  # type: ignore[arg-type]


class _FakeResponse:
    def __init__(
        self,
        *,
        payload: Mapping[str, Any] | None = None,
        status_error: BaseException | None = None,
    ) -> None:
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self) -> Mapping[str, Any]:
        assert self._payload is not None
        return self._payload


class _RecordingPost:
    def __init__(self, response: _FakeResponse | BaseException) -> None:
        self.calls: list[dict[str, object]] = []
        self._response = response

    def __call__(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self._response, BaseException):
            raise self._response
        return self._response


def test_missing_base_url_raises_config_error() -> None:
    with pytest.raises(OllamaConfigError, match="OLLAMA_BASE_URL"):
        OllamaChat(_settings(base_url=None))


def test_complete_returns_ask_result_from_injected_post() -> None:
    post = _RecordingPost(
        _FakeResponse(
            payload={
                "model": "llama3.2",
                "choices": [{"message": {"content": "Local answer."}}],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            }
        )
    )
    chat = OllamaChat(_settings(), post=post)

    result = chat.complete(
        "You answer from context.",
        (Message(role="user", content="What is Kernector?"),),
        {"temperature": 0.1},
    )

    assert result.content == "Local answer."
    assert result.model == "llama3.2"
    assert result.usage == Usage(
        prompt_tokens=3,
        completion_tokens=2,
        total_tokens=5,
        cost=None,
    )
    assert result.settings == {"temperature": 0.1}
    assert len(post.calls) == 1
    assert post.calls[0]["url"] == "http://localhost:11434/v1/chat/completions"


def test_complete_raises_provider_error_on_connection_failure() -> None:
    upstream = requests.exceptions.ConnectionError("connection refused: secret-token")
    chat = OllamaChat(_settings(), post=_RecordingPost(upstream))

    with pytest.raises(
        ProviderError, match="Ollama chat provider could not be reached"
    ) as raised:
        chat.complete("system", (Message(role="user", content="hi"),), {})

    assert "secret-token" not in str(raised.value)
    assert "connection refused" not in str(raised.value)
    assert raised.value.__cause__ is upstream


def test_complete_raises_provider_error_on_parse_failure() -> None:
    chat = OllamaChat(
        _settings(),
        post=_RecordingPost(_FakeResponse(payload={"choices": []})),
    )

    with pytest.raises(
        ProviderError, match="Ollama chat response could not be parsed"
    ) as raised:
        chat.complete("system", (Message(role="user", content="hi"),), {})

    assert isinstance(raised.value.__cause__, IndexError)
