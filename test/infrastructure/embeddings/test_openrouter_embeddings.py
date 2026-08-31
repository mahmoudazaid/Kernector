"""OpenRouter embeddings adapter, tested through an injected client."""

import pytest

from domain.errors import ProviderError
from infrastructure.config import OpenRouterSettings
from infrastructure.embeddings.openrouter import (
    EmbeddingConfigError,
    OpenRouterEmbeddings,
)


def _settings(**overrides: object) -> OpenRouterSettings:
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


class _FakeClient:
    def __init__(
        self,
        *,
        vectors: list[list[float]] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._vectors = vectors or [[0.1, 0.2]]
        self._error = error
        self.embed_documents_calls: list[list[str]] = []
        self.embed_query_calls: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embed_documents_calls.append(texts)
        if self._error is not None:
            raise self._error
        return self._vectors

    def embed_query(self, text: str) -> list[float]:
        self.embed_query_calls.append(text)
        if self._error is not None:
            raise self._error
        return self._vectors[0]


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("api_key", None, "OPENROUTER_API_KEY"),
        ("api_key", "", "OPENROUTER_API_KEY"),
        ("base_url", None, "OPENROUTER_BASE_URL"),
        ("base_url", "", "OPENROUTER_BASE_URL"),
        ("embedding_model", None, "OPENROUTER_EMBEDDING_MODEL"),
        ("embedding_model", "", "OPENROUTER_EMBEDDING_MODEL"),
    ],
)
def test_missing_config_raises_at_construction(
    field: str, value: object, match: str
) -> None:
    with pytest.raises(EmbeddingConfigError, match=match):
        OpenRouterEmbeddings(_settings(**{field: value}))


def test_embed_documents_returns_vectors_from_client() -> None:
    client = _FakeClient(vectors=[[1.0, 2.0], [3.0, 4.0]])
    embeddings = OpenRouterEmbeddings(_settings(), client=client)

    result = embeddings.embed_documents(["a", "b"])

    assert result == [[1.0, 2.0], [3.0, 4.0]]
    assert client.embed_documents_calls == [["a", "b"]]


def test_embed_documents_empty_skips_client() -> None:
    client = _FakeClient(error=RuntimeError("should not run"))
    embeddings = OpenRouterEmbeddings(_settings(), client=client)

    assert embeddings.embed_documents([]) == []
    assert client.embed_documents_calls == []


def test_embed_query_returns_vector_from_client() -> None:
    client = _FakeClient(vectors=[[0.5, 0.25]])
    embeddings = OpenRouterEmbeddings(_settings(), client=client)

    assert embeddings.embed_query("hello") == [0.5, 0.25]
    assert client.embed_query_calls == ["hello"]


def test_embed_query_raises_provider_error_without_vendor_text() -> None:
    upstream = RuntimeError("401 api-key-leaked-in-body")
    embeddings = OpenRouterEmbeddings(
        _settings(), client=_FakeClient(error=upstream)
    )

    with pytest.raises(
        ProviderError, match="OpenRouter embedding provider could not be reached"
    ) as raised:
        embeddings.embed_query("hello")

    assert "api-key-leaked-in-body" not in str(raised.value)
    assert raised.value.__cause__ is upstream


def test_embed_documents_raises_provider_error_without_vendor_text() -> None:
    upstream = RuntimeError("rate limit detail")
    embeddings = OpenRouterEmbeddings(
        _settings(), client=_FakeClient(error=upstream)
    )

    with pytest.raises(ProviderError) as raised:
        embeddings.embed_documents(["a"])

    assert "rate limit detail" not in str(raised.value)
    assert raised.value.__cause__ is upstream
