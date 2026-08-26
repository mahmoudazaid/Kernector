"""Composition root: the outermost edge, where the layers are joined."""

from composition.container import (
    available_providers,
    build_ask_service,
    build_chat_model,
    build_embedding_model,
    build_prompt_repository,
    build_vector_store,
    probe_ollama,
)


from infrastructure.config import Settings, load_settings

__all__ = [
    "Settings",
    "available_providers",
    "build_ask_service",
    "build_chat_model",
    "build_embedding_model",
    "build_prompt_repository",
    "build_vector_store",
    "load_settings",
    "probe_ollama",
]
