"""Composition root: the only place that constructs infrastructure."""

from collections.abc import Callable, Mapping
from dataclasses import replace

from application.ask_service import AskService
from application.errors import ConfigurationError
from application.ingest_knowledge import IngestKnowledge
from composition.errors import KnowledgeLoadError
from domain.knowledge import SourceDocument
from domain.ports import ChatModel, EmbeddingModel, PromptRepository, VectorStore
from infrastructure.config import Settings, load_settings
from infrastructure.embeddings.openrouter import (
    EmbeddingConfigError,
    OpenRouterEmbeddings,
)
from infrastructure.knowledge.corpus import CorpusLoadError, load_knowledge_corpus
from infrastructure.llm.ollama import OllamaChat
from infrastructure.llm.ollama import probe_ollama as _probe_ollama
from infrastructure.llm.openrouter import OpenRouterChat
from infrastructure.prompts.markdown_repository import MarkdownPromptRepository
from infrastructure.vectorstore.chroma import ChromaVectorStore



def _build_openrouter(
    settings: Settings, model: str | None, base_url: str | None
) -> ChatModel:
    config = settings.openrouter
    if model:
        config = replace(config, model=model)
    return OpenRouterChat(config)


def _build_ollama(
    settings: Settings, model: str | None, base_url: str | None
) -> ChatModel:
    config = settings.ollama
    if model:
        config = replace(config, model=model)
    if base_url:
        config = replace(config, base_url=base_url)
    return OllamaChat(config)


_CHAT_MODELS: Mapping[str, Callable[[Settings, str | None, str | None], ChatModel]] = {
    "openrouter": _build_openrouter,
    "ollama": _build_ollama,
}


def available_providers() -> tuple[str, ...]:
    """The provider keys the composition root knows how to build."""
    return tuple(_CHAT_MODELS)


def load_runtime_settings() -> Settings:
    """Load environment settings for presentation and other composition callers.

    Wraps ``infrastructure.config.load_settings`` so presentation never imports
    infrastructure. Expected parse failures become ``ConfigurationError``.

    Returns:
        Settings: Frozen runtime configuration for composition factories.

    Raises:
        ConfigurationError: If environment values fail known config validation.
    """
    try:
        return load_settings()
    except ValueError as error:
        raise ConfigurationError(str(error)) from error


def load_knowledge_documents(settings: Settings) -> tuple[SourceDocument, ...]:
    """Load normalized knowledge documents from the configured corpus path.

    Args:
        settings (Settings): Runtime settings whose knowledge.corpus_path is used.

    Returns:
        tuple[SourceDocument, ...]: Normalized documents for ingestion.

    Raises:
        KnowledgeLoadError: If the corpus file cannot be loaded or validated.
    """
    try:
        return load_knowledge_corpus(settings.knowledge.corpus_path)
    except CorpusLoadError as error:
        raise KnowledgeLoadError(str(error)) from error


def build_chat_model(
    settings: Settings,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> ChatModel:
    """Build a chat model, applying runtime overrides over the loaded settings.

    `base_url` applies to Ollama only; OpenRouter ignores it.
    """
    provider = provider or settings.provider
    factory = _CHAT_MODELS.get(provider)
    if factory is None:
        raise ValueError(
            f"Unknown provider {provider!r}. Expected one of {sorted(_CHAT_MODELS)}."
        )
    return factory(settings, model, base_url)


def build_embedding_model(settings: Settings) -> EmbeddingModel:
    return OpenRouterEmbeddings(settings.openrouter)


def build_vector_store(settings: Settings) -> VectorStore:
    return ChromaVectorStore(settings.chroma)


def build_ingest_knowledge(settings: Settings) -> IngestKnowledge:
    """Wire the ingest use case from the loaded settings.

    Only the embedding adapter's own configuration failure is mapped to a typed
    `ConfigurationError`. Vector-store failures keep `ChromaStoreError`: a
    missing credential and an unreadable collection are different problems, and
    relabelling the latter would send a caller looking in the wrong place.

    Pure, like `build_vector_store`: a fresh instance per call, so no open
    SQLite handle is retained across callers.

    Raises:
        ConfigurationError: The embedding credentials are missing or unusable.
    """
    try:
        embedding_model = build_embedding_model(settings)
    except EmbeddingConfigError as exc:
        raise ConfigurationError(str(exc)) from exc
    vector_store = build_vector_store(settings)
    return IngestKnowledge(
        embedding_model,
        vector_store,
        chunk_size=settings.chunking.chunk_size,
        chunk_overlap=settings.chunking.chunk_overlap,
    )


def build_prompt_repository() -> PromptRepository:
    return MarkdownPromptRepository()


def build_ask_service(chat_model: ChatModel) -> AskService:
    return AskService(chat_model)


def probe_ollama(settings: Settings, base_url: str) -> dict:
    """Reachability check, with the timeout taken from settings."""
    return _probe_ollama(base_url, settings.ollama.timeout)
