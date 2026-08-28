"""Composition root: the outermost edge, where the layers are joined."""

from composition.container import (
    SUPPORTED_UPLOAD_SUFFIXES,
    available_providers,
    build_ask_service,
    build_chat_model,
    build_embedding_model,
    build_ingest_knowledge,
    build_prompt_repository,
    build_vector_store,
    ingest_uploaded_document,
    load_knowledge_documents,
    load_runtime_settings,
    probe_ollama,
)
from composition.errors import DocumentUploadError, KnowledgeLoadError
from infrastructure.config import Settings

__all__ = [
    "DocumentUploadError",
    "KnowledgeLoadError",
    "SUPPORTED_UPLOAD_SUFFIXES",
    "Settings",
    "available_providers",
    "build_ask_service",
    "build_chat_model",
    "build_embedding_model",
    "build_ingest_knowledge",
    "build_prompt_repository",
    "build_vector_store",
    "ingest_uploaded_document",
    "load_knowledge_documents",
    "load_runtime_settings",
    "probe_ollama",
]
