"""Configuration loaded at the edge. Only the composition root calls load_settings()."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class OpenRouterSettings:
    api_key: str | None
    base_url: str | None
    model: str | None
    models: tuple[str, ...]
    embedding_model: str
    timeout: float


@dataclass(frozen=True, slots=True)
class OllamaSettings:
    base_url: str | None
    model: str | None
    timeout: float


@dataclass(frozen=True, slots=True)
class ChunkingSettings:
    chunk_size: int
    chunk_overlap: int


@dataclass(frozen=True, slots=True)
class Settings:
    provider: str
    max_input_length: int
    openrouter: OpenRouterSettings
    ollama: OllamaSettings
    chunking: ChunkingSettings


def load_settings() -> Settings:
    """Read the environment once. The composition root is the only caller."""
    load_dotenv(override=True)
    return Settings(
        provider=os.getenv("LLM_PROVIDER", "openrouter").lower(),
        max_input_length=int(os.getenv("MAX_INPUT_LENGTH", "10000")),
        openrouter=OpenRouterSettings(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=os.getenv("OPENROUTER_BASE_URL"),
            model=os.getenv("OPENROUTER_MODEL"),
            models=_csv(os.getenv("OPENROUTER_MODELS", "")),
            embedding_model=os.getenv(
                "OPENROUTER_EMBEDDING_MODEL", "qwen/qwen3-embedding-8b"
            ),
            timeout=float(os.getenv("OPENROUTER_TIMEOUT", "120")),
        ),
        ollama=OllamaSettings(
            base_url=os.getenv("OLLAMA_BASE_URL"),
            model=os.getenv("OLLAMA_MODEL"),
            timeout=float(os.getenv("OLLAMA_TIMEOUT", "120")),
        ),
        chunking=_load_chunking_settings(),
    )


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _env_int(name: str, default: str) -> int:
    raw = os.getenv(name, default)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _load_chunking_settings() -> ChunkingSettings:
    chunk_size = _env_int("CHUNK_SIZE", "500")
    chunk_overlap = _env_int("CHUNK_OVERLAP", "50")
    if chunk_size <= 0:
        raise ValueError(f"CHUNK_SIZE must be > 0, got {chunk_size}")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError(
            "CHUNK_OVERLAP must satisfy 0 <= overlap < CHUNK_SIZE, "
            f"got overlap={chunk_overlap}, size={chunk_size}"
        )
    return ChunkingSettings(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
