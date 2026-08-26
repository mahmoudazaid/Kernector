"""Configuration loaded at the edge. Only the composition root calls load_settings()."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
class ChromaSettings:
    persist_path: Path
    collection: str

@dataclass(frozen=True, slots=True)
class Settings:
    provider: str
    max_input_length: int
    openrouter: OpenRouterSettings
    ollama: OllamaSettings
    chunking: ChunkingSettings
    chroma: ChromaSettings


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
        chroma=_load_chroma_settings(),
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

def _resolve_under_project_root(raw: str) -> Path:
    """Expand `~`, keep absolute paths, resolve relative ones against the repo root.

    Deliberately not resolved against the CWD, so the store lands in the same
    place whether the app is launched from the repo root or elsewhere. Mirrors
    `infrastructure/prompts/markdown_repository.py`, which uses `parents[2]`
    from one directory deeper.
    """
    path = Path(raw).expanduser()
    return path if path.is_absolute() else _PROJECT_ROOT / path


def _load_chroma_settings() -> ChromaSettings:
    collection = os.getenv("CHROMA_COLLECTION", "kernector_knowledge")
    if not collection.strip():
        raise ValueError(f"CHROMA_COLLECTION must be non-empty, got {collection!r}")
    persist_path = os.getenv("CHROMA_PERSIST_PATH", "data/chroma")
    if not persist_path.strip():
        raise ValueError(
            f"CHROMA_PERSIST_PATH must be non-empty, got {persist_path!r}"
        )
    return ChromaSettings(
        persist_path=_resolve_under_project_root(persist_path),
        collection=collection,
    )
