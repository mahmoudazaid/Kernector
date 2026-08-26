"""Composition root: the only place that constructs infrastructure."""

from collections.abc import Callable, Mapping
from dataclasses import replace

from application.ask_service import AskService
from domain.ports import ChatModel, EmbeddingModel, PromptRepository, VectorStore
from infrastructure.config import Settings
from infrastructure.embeddings.openrouter import OpenRouterEmbeddings
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


def build_prompt_repository() -> PromptRepository:
    return MarkdownPromptRepository()


def build_ask_service(chat_model: ChatModel) -> AskService:
    return AskService(chat_model)


def probe_ollama(settings: Settings, base_url: str) -> dict:
    """Reachability check, with the timeout taken from settings."""
    return _probe_ollama(base_url, settings.ollama.timeout)
