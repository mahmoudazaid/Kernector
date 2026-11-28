"""OpenAI embeddings adapter (#462)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from langchain_openai import OpenAIEmbeddings as LangChainOpenAIEmbeddings

from domain.knowledge import Vector
from infrastructure.config import OpenAISettings
from infrastructure.llm.provider_failures import classify_provider_failure

_CONNECTION_FAILURE_MESSAGE = "The OpenAI embedding provider could not be reached."


class EmbeddingConfigError(RuntimeError):
    """OpenAI embedding credentials or model are missing or unusable."""


class _EmbeddingClient(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class OpenAIEmbeddings:
    """EmbeddingModel backed by OpenAI."""

    def __init__(
        self,
        config: OpenAISettings,
        *,
        client: _EmbeddingClient | None = None,
    ) -> None:
        _require_embedding_config(config)
        self._client: _EmbeddingClient = client or LangChainOpenAIEmbeddings(
            model=config.embedding_model,
            api_key=config.api_key,
            timeout=config.timeout,
            check_embedding_ctx_length=False,
        )

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Vector]:
        if not texts:
            return []
        try:
            return self._client.embed_documents(list(texts))
        except Exception as exc:
            raise classify_provider_failure(
                exc, fallback_message=_CONNECTION_FAILURE_MESSAGE
            ) from None

    def embed_query(self, text: str) -> Vector:
        try:
            return self._client.embed_query(text)
        except Exception as exc:
            raise classify_provider_failure(
                exc, fallback_message=_CONNECTION_FAILURE_MESSAGE
            ) from None


def _require_embedding_config(config: OpenAISettings) -> None:
    if not config.api_key:
        raise EmbeddingConfigError(
            "Missing OPENAI_API_KEY. Add it to .env before embedding."
        )
    if not config.embedding_model:
        raise EmbeddingConfigError(
            "Missing OPENAI_EMBEDDING_MODEL. Add it to .env before embedding."
        )
