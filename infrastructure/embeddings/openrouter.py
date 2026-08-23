"""OpenRouter embeddings adapter."""

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from langchain_openai import OpenAIEmbeddings

from domain.knowledge import Vector
from infrastructure.config import OpenRouterSettings


class OpenRouterEmbeddings:
    """EmbeddingModel backed by OpenRouter."""

    def __init__(self, config: OpenRouterSettings) -> None:
        _require_embedding_config(config)
        self._client = OpenAIEmbeddings(
            model=config.embedding_model,
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
            check_embedding_ctx_length=False,
        )

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Vector]:
        if not texts:
            return []
        return self._client.embed_documents(list(texts))

    def embed_query(self, text: str) -> Vector:
        return self._client.embed_query(text)


def _require_embedding_config(config: OpenRouterSettings) -> None:
    """Fail fast when the embedding credentials are absent."""
    if not config.api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY. Add it to .env before embedding.")
    if not config.base_url:
        raise RuntimeError("Missing OPENROUTER_BASE_URL. Add it to .env before embedding.")
    if not config.embedding_model:
        raise RuntimeError(
            "Missing OPENROUTER_EMBEDDING_MODEL. Add it to .env before embedding."
        )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    vector_a = np.asarray(a, dtype=float)
    vector_b = np.asarray(b, dtype=float)
    if vector_a.shape != vector_b.shape:
        raise ValueError(f"Vector length mismatch: {vector_a.size} vs {vector_b.size}")
    norm_a = np.linalg.norm(vector_a)
    norm_b = np.linalg.norm(vector_b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(vector_a, vector_b) / (norm_a * norm_b))


def save_records(records: list[dict], path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")


def load_records(path: str) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
