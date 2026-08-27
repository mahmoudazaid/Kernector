"""Composition root: the outermost edge, where the layers are joined."""

from composition.container import (
    available_providers,
    build_ask_service,
    build_chat_model,
    build_embedding_model,
    build_ingest_knowledge,
    build_prompt_repository,
    build_vector_store,
    load_knowledge_documents,
    load_runtime_settings,
    probe_ollama,
)
from composition.errors import KnowledgeLoadError
from infrastructure.config import Settings

__all__ = [
    "KnowledgeLoadError",
    "Settings",
    "available_providers",
    "build_ask_service",
    "build_chat_model",
    "build_embedding_model",
    "build_ingest_knowledge",
    "build_prompt_repository",
    "build_vector_store",
    "load_knowledge_documents",
    "load_runtime_settings",
    "probe_ollama",
]
