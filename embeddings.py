"""OpenRouter embedding client and vector similarity helpers.

Required environment variables (see .env):
  OPENROUTER_API_KEY          OpenRouter API key.
  OPENROUTER_BASE_URL         OpenRouter OpenAI-compatible endpoint.
  OPENROUTER_EMBEDDING_MODEL  Embedding model id (default qwen/qwen3-embedding-8b).

Usage:
    from embeddings import embed_texts, cosine_similarity

    vectors = embed_texts(["I forgot my password", "How do I reset my login?"])
    print(cosine_similarity(vectors[0], vectors[1]))
"""

import json
from pathlib import Path
import numpy as np
from langchain_openai import OpenAIEmbeddings
import config

def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    require_config()
    if not texts:
        return []
    client = make_openrouter_embeddings(model)
    return client.embed_documents(texts)

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

def make_openrouter_embeddings(model: str | None = None) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=model or config.OPENROUTER_EMBEDDING_MODEL,
        api_key=config.OPENROUTER_API_KEY,
        base_url=config.OPENROUTER_BASE_URL,
        timeout=config.OPENROUTER_TIMEOUT,
        check_embedding_ctx_length=False,
    )

def require_config() -> None:
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("Missing OPENROUTER_API_KEY. Add it to .env before embedding.")
    if not config.OPENROUTER_BASE_URL:
        raise RuntimeError("Missing OPENROUTER_BASE_URL. Add it to .env before embedding.")
    if not config.OPENROUTER_EMBEDDING_MODEL:
        raise RuntimeError("Missing OPENROUTER_EMBEDDING_MODEL. Add it to .env before embedding.")

def save_records(records: list[dict], path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")


def load_records(path: str) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
