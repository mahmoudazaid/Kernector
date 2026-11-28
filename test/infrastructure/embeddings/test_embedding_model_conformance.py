"""EmbeddingModel conformance across embedding-capable providers (#462)."""

from __future__ import annotations

from importlib.util import find_spec
from typing import Any

import pytest

from domain.errors import ProviderError
from infrastructure.config import GeminiSettings, OpenAISettings, OpenRouterSettings
from infrastructure.embeddings.gemini import (
    EmbeddingConfigError as GeminiEmbeddingConfigError,
)
from infrastructure.embeddings.gemini import GeminiEmbeddings
from infrastructure.embeddings.openai import (
    EmbeddingConfigError as OpenAIEmbeddingConfigError,
)
from infrastructure.embeddings.openai import OpenAIEmbeddings
from infrastructure.embeddings.openrouter import (
    EmbeddingConfigError as OpenRouterEmbeddingConfigError,
)
from infrastructure.embeddings.openrouter import OpenRouterEmbeddings


class _FakeClient:
    def __init__(
        self,
        *,
        documents: list[list[float]] | None = None,
        query: list[float] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._documents = documents or [[0.1, 0.2]]
        self._query = query or [0.3, 0.4]
        self._error = error

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._error is not None:
            raise self._error
        return [self._documents[0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        if self._error is not None:
            raise self._error
        return self._query


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


def _gemini_settings(**overrides: object) -> GeminiSettings:
    values: dict[str, object] = {
        "api_key": "gem-key",
        "model": "gemini-2.0-flash",
        "embedding_model": "models/gemini-embedding-2",
        "timeout": 30.0,
    }
    values.update(overrides)
    return GeminiSettings(**values)  # type: ignore[arg-type]


def _build_openrouter(client: _FakeClient) -> Any:
    return OpenRouterEmbeddings(_openrouter_settings(), client=client)


def _build_openai(client: _FakeClient) -> Any:
    return OpenAIEmbeddings(_openai_settings(), client=client)


def _build_gemini(client: _FakeClient) -> Any:
    return GeminiEmbeddings(_gemini_settings(), client=client)


_CASES = [
    ("openrouter", _build_openrouter, "OpenRouter"),
    ("openai", _build_openai, "OpenAI"),
    ("gemini", _build_gemini, "Gemini"),
]


@pytest.mark.parametrize(("provider", "builder", "label"), _CASES)
def test_embed_documents_and_query(provider: str, builder: Any, label: str) -> None:
    model = builder(_FakeClient(documents=[[1.0, 2.0]], query=[3.0, 4.0]))
    assert list(model.embed_documents(["a", "b"])) == [[1.0, 2.0], [1.0, 2.0]]
    assert list(model.embed_query("q")) == [3.0, 4.0]


@pytest.mark.parametrize(("provider", "builder", "label"), _CASES)
def test_empty_documents_return_empty(provider: str, builder: Any, label: str) -> None:
    model = builder(_FakeClient())
    assert list(model.embed_documents([])) == []


@pytest.mark.parametrize(("provider", "builder", "label"), _CASES)
def test_embed_failures_are_sanitized(provider: str, builder: Any, label: str) -> None:
    model = builder(_FakeClient(error=RuntimeError("leak sk-secret")))
    with pytest.raises(ProviderError) as raised:
        model.embed_query("hi")
    assert "sk-secret" not in str(raised.value)
    assert "sk-secret" not in repr(raised.value)
    assert raised.value.__cause__ is None


def test_anthropic_embeddings_module_is_absent() -> None:
    assert find_spec("infrastructure.embeddings.anthropic") is None


@pytest.mark.parametrize(
    ("builder", "error_type"),
    [
        (lambda: OpenRouterEmbeddings(_openrouter_settings(api_key="")), OpenRouterEmbeddingConfigError),
        (lambda: OpenAIEmbeddings(_openai_settings(api_key="")), OpenAIEmbeddingConfigError),
        (lambda: GeminiEmbeddings(_gemini_settings(api_key="")), GeminiEmbeddingConfigError),
    ],
)
def test_missing_credentials_raise_config_error(builder: Any, error_type: type[Exception]) -> None:
    with pytest.raises(error_type):
        builder()
