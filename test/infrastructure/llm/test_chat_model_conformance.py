"""ChatModel conformance across native providers (#462)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import requests
from langchain_core.messages import AIMessage
from openai import AuthenticationError

from domain.errors import ProviderAuthError, ProviderError
from domain.models import Message
from infrastructure.config import (
    AnthropicSettings,
    GeminiSettings,
    OllamaSettings,
    OpenAISettings,
    OpenRouterSettings,
)
from infrastructure.llm.anthropic import AnthropicChat
from infrastructure.llm.anthropic import ChatConfigError as AnthropicConfigError
from infrastructure.llm.gemini import ChatConfigError as GeminiConfigError
from infrastructure.llm.gemini import GeminiChat
from infrastructure.llm.ollama import OllamaChat, OllamaConfigError
from infrastructure.llm.openai import ChatConfigError as OpenAIConfigError
from infrastructure.llm.openai import OpenAIChat
from infrastructure.llm.openrouter import ChatConfigError as OpenRouterConfigError
from infrastructure.llm.openrouter import OpenRouterChat


class _FakeChat:
    def __init__(
        self,
        message: object | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self._message = message
        self._error = error
        self.settings: Mapping[str, object] | None = None

    def __call__(self, prompt_value: object, **_kwargs: object) -> object:
        if self._error is not None:
            raise self._error
        assert self._message is not None
        return self._message


class _RecordingFactory:
    def __init__(self, chat: _FakeChat) -> None:
        self.chat = chat
        self.calls = 0
        self.settings: Mapping[str, object] | None = None
        self.config: object | None = None

    def __call__(self, config: object, settings: Mapping[str, object]) -> _FakeChat:
        self.calls += 1
        self.config = config
        self.settings = settings
        self.chat.settings = settings
        return self.chat


class _OllamaPost:
    def __init__(
        self,
        *,
        payload: dict[str, object] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._payload = payload or {
            "choices": [{"message": {"content": "ollama-ok"}}],
            "model": "llama3.2",
            "usage": {},
        }
        self._error = error
        self.calls: list[dict[str, object]] = []

    def __call__(self, url: str, **kwargs: object) -> object:
        self.calls.append({"url": url, **kwargs})
        if self._error is not None:
            raise self._error

        class _Resp:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return self._outer._payload

            def __init__(self, outer: _OllamaPost) -> None:
                self._outer = outer

        return _Resp(self)


def _openrouter_settings(**overrides: object) -> OpenRouterSettings:
    values: dict[str, object] = {
        "api_key": "sk-test",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "chat/model",
        "models": (),
        "embedding_model": "embed/model",
        "rewrite_model": "rewrite/model",
        "timeout": 30.0,
    }
    values.update(overrides)
    return OpenRouterSettings(**values)  # type: ignore[arg-type]


def _openai_settings(**overrides: object) -> OpenAISettings:
    values: dict[str, object] = {
        "api_key": "sk-openai",
        "model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small",
        "timeout": 30.0,
    }
    values.update(overrides)
    return OpenAISettings(**values)  # type: ignore[arg-type]


def _anthropic_settings(**overrides: object) -> AnthropicSettings:
    values: dict[str, object] = {
        "api_key": "sk-ant",
        "model": "claude-sonnet-4-5",
        "timeout": 30.0,
    }
    values.update(overrides)
    return AnthropicSettings(**values)  # type: ignore[arg-type]


def _gemini_settings(**overrides: object) -> GeminiSettings:
    values: dict[str, object] = {
        "api_key": "gem-key",
        "model": "gemini-2.0-flash",
        "embedding_model": "models/gemini-embedding-2",
        "timeout": 30.0,
    }
    values.update(overrides)
    return GeminiSettings(**values)  # type: ignore[arg-type]


def _ollama_settings(**overrides: object) -> OllamaSettings:
    values: dict[str, object] = {
        "base_url": "http://localhost:11434",
        "model": "llama3.2",
        "timeout": 30.0,
    }
    values.update(overrides)
    return OllamaSettings(**values)  # type: ignore[arg-type]


def _build_openrouter(fake: _FakeChat) -> tuple[Any, _RecordingFactory]:
    factory = _RecordingFactory(fake)
    return OpenRouterChat(_openrouter_settings(), model_factory=factory), factory


def _build_openai(fake: _FakeChat) -> tuple[Any, _RecordingFactory]:
    factory = _RecordingFactory(fake)
    return OpenAIChat(_openai_settings(), model_factory=factory), factory


def _build_anthropic(fake: _FakeChat) -> tuple[Any, _RecordingFactory]:
    factory = _RecordingFactory(fake)
    return AnthropicChat(_anthropic_settings(), model_factory=factory), factory


def _build_gemini(fake: _FakeChat) -> tuple[Any, _RecordingFactory]:
    factory = _RecordingFactory(fake)
    return GeminiChat(_gemini_settings(), model_factory=factory), factory


ProviderCase = tuple[str, Callable[[_FakeChat], tuple[Any, _RecordingFactory]], str]

_LANGCHAIN_CASES: list[ProviderCase] = [
    ("openrouter", _build_openrouter, "OpenRouter"),
    ("openai", _build_openai, "OpenAI"),
    ("anthropic", _build_anthropic, "Anthropic"),
    ("gemini", _build_gemini, "Gemini"),
]


@pytest.mark.parametrize(("provider", "builder", "label"), _LANGCHAIN_CASES)
def test_complete_returns_ask_result(
    provider: str,
    builder: Callable[[_FakeChat], tuple[Any, _RecordingFactory]],
    label: str,
) -> None:
    fake = _FakeChat(
        AIMessage(
            content=f"{label} answer",
            usage_metadata={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        )
    )
    chat, factory = builder(fake)
    result = chat.complete(
        "system",
        (Message(role="user", content="hi"),),
        {"temperature": 0.2},
    )
    assert result.content == f"{label} answer"
    assert result.settings == {"temperature": 0.2}
    assert factory.calls == 1
    assert factory.settings == {"temperature": 0.2}


@pytest.mark.parametrize(("provider", "builder", "label"), _LANGCHAIN_CASES)
def test_complete_sanitizes_classified_failures(
    provider: str,
    builder: Callable[[_FakeChat], tuple[Any, _RecordingFactory]],
    label: str,
) -> None:
    upstream = AuthenticationError(
        "bad key sk-secret",
        response=httpx.Response(401, request=httpx.Request("POST", "https://example")),
        body={"error": {"message": "sk-secret"}},
    )
    chat, _factory = builder(_FakeChat(error=upstream))
    with pytest.raises(ProviderAuthError) as raised:
        chat.complete("system", (Message(role="user", content="hi"),), {})
    assert "sk-secret" not in str(raised.value)
    assert "sk-secret" not in repr(raised.value)
    assert raised.value.__cause__ is None


def test_ollama_complete_returns_ask_result() -> None:
    post = _OllamaPost()
    chat = OllamaChat(_ollama_settings(), post=post)
    result = chat.complete(
        "system",
        (Message(role="user", content="hi"),),
        {"temperature": 0.1},
    )
    assert result.content == "ollama-ok"
    assert result.settings == {"temperature": 0.1}


def test_ollama_complete_sanitizes_failures() -> None:
    upstream = requests.exceptions.HTTPError(
        "401 sk-secret",
        response=type("Resp", (), {"status_code": 401})(),
    )
    chat = OllamaChat(_ollama_settings(), post=_OllamaPost(error=upstream))
    with pytest.raises(ProviderAuthError) as raised:
        chat.complete("system", (Message(role="user", content="hi"),), {})
    assert "sk-secret" not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    ("builder", "config_error", "bad_kwargs"),
    [
        (
            lambda: OpenRouterChat(_openrouter_settings(api_key="")),
            OpenRouterConfigError,
            {},
        ),
        (lambda: OpenAIChat(_openai_settings(api_key="")), OpenAIConfigError, {}),
        (
            lambda: AnthropicChat(_anthropic_settings(api_key="")),
            AnthropicConfigError,
            {},
        ),
        (lambda: GeminiChat(_gemini_settings(api_key="")), GeminiConfigError, {}),
        (lambda: OllamaChat(_ollama_settings(base_url=None)), OllamaConfigError, {}),
    ],
)
def test_missing_credentials_raise_config_error(
    builder: Callable[[], object],
    config_error: type[Exception],
    bad_kwargs: dict[str, object],
) -> None:
    with pytest.raises(config_error):
        builder()


@pytest.mark.parametrize(("provider", "builder", "label"), _LANGCHAIN_CASES)
def test_parse_failure_has_no_unsafe_cause(
    provider: str,
    builder: Callable[[_FakeChat], tuple[Any, _RecordingFactory]],
    label: str,
) -> None:
    chat, _factory = builder(_FakeChat(SimpleNamespace(content="", usage_metadata=None)))
    with pytest.raises(ProviderError) as raised:
        chat.complete("system", (Message(role="user", content="hi"),), {})
    assert raised.value.__cause__ is None


def test_gemini_flattens_content_block_lists() -> None:
    fake = _FakeChat(
        AIMessage(content=[{"type": "text", "text": "hello from gemini-3"}])
    )
    chat, _factory = _build_gemini(fake)
    result = chat.complete("system", (Message(role="user", content="hi"),), {})
    assert result.content == "hello from gemini-3"


def test_anthropic_drops_sampling_for_claude_sonnet_5_5() -> None:
    from infrastructure.llm.anthropic import _sampling_kwargs_for_model

    filtered = _sampling_kwargs_for_model(
        "claude-sonnet-5-5",
        {"temperature": 0.3, "max_tokens": 1000, "top_p": 1.0},
    )
    assert filtered == {"max_tokens": 1000}
    kept = _sampling_kwargs_for_model(
        "claude-sonnet-4-5",
        {"temperature": 0.3, "max_tokens": 1000, "top_p": 1.0},
    )
    assert kept == {"temperature": 0.3, "max_tokens": 1000, "top_p": 1.0}
