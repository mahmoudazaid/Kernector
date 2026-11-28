"""Gemini embeddings adapter (#462)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from domain.knowledge import Vector
from infrastructure.config import GeminiSettings
from infrastructure.llm.provider_failures import classify_provider_failure

_CONNECTION_FAILURE_MESSAGE = "The Gemini embedding provider could not be reached."


class EmbeddingConfigError(RuntimeError):
    """Gemini embedding credentials or model are missing or unusable."""


class _EmbeddingClient(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class GeminiEmbeddings:
    """EmbeddingModel backed by Google Gemini."""

    def __init__(
        self,
        config: GeminiSettings,
        *,
        client: _EmbeddingClient | None = None,
    ) -> None:
        _require_embedding_config(config)
        self._client: _EmbeddingClient = client or GoogleGenerativeAIEmbeddings(
            model=config.embedding_model,
            google_api_key=config.api_key,
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


def _require_embedding_config(config: GeminiSettings) -> None:
    if not config.api_key:
        raise EmbeddingConfigError(
            "Missing GEMINI_API_KEY. Add it to .env before embedding."
        )
    if not config.embedding_model:
        raise EmbeddingConfigError(
            "Missing GEMINI_EMBEDDING_MODEL. Add it to .env before embedding."
        )
