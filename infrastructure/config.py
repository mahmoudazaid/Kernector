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
class Settings:
    provider: str
    max_input_length: int
    openrouter: OpenRouterSettings
    ollama: OllamaSettings


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
    )


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())
