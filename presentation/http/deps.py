"""FastAPI dependencies for the HTTP presentation adapter."""

from functools import lru_cache
from typing import Annotated, Protocol

from fastapi import Depends

from application.runtime_settings import GetRuntimeSettings, ProbeOllamaStatus
from composition import (
    GroundedAsk,
    Settings,
    build_chat_model,
    build_prompt_repository,
    build_probe_ollama_status,
    build_runtime_settings,
    build_tool_augmented_ask,
    build_vector_store,
    load_runtime_settings,
)
from domain.ports import PromptRepository, VectorStore
from presentation.http.schemas import ChatRuntimeRequest


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Resolve runtime settings once per process through composition.

    Mirrors Streamlit's ``@st.cache_resource`` settings load: avoids re-running
    ``configure_logging`` / ``load_dotenv(override=True)`` on every request.
    """
    return load_runtime_settings()


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    """Process-cached vector store (hybrid BM25 hydrate once, like Streamlit)."""
    return build_vector_store(get_settings())


@lru_cache(maxsize=1)
def get_prompt_repository() -> PromptRepository:
    """Process-cached prompt repository."""
    return build_prompt_repository(get_settings())


def get_runtime_settings(
    settings: Annotated[Settings, Depends(get_settings)],
) -> GetRuntimeSettings:
    """Build the runtime settings catalog use case for this request."""
    return build_runtime_settings(settings)


def get_probe_ollama_status(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProbeOllamaStatus:
    """Build the Ollama probe use case for this request."""
    return build_probe_ollama_status(settings)


class AskFactory(Protocol):
    """Build a ``GroundedAsk`` for one request's runtime selection."""

    def __call__(self, runtime: ChatRuntimeRequest | None) -> GroundedAsk: ...


def get_ask_factory(
    settings: Annotated[Settings, Depends(get_settings)],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
    prompt_repository: Annotated[PromptRepository, Depends(get_prompt_repository)],
) -> AskFactory:
    """Return a factory that builds ask with per-request provider/model overrides."""

    def factory(runtime: ChatRuntimeRequest | None) -> GroundedAsk:
        provider = None if runtime is None else runtime.provider
        model = None if runtime is None else runtime.model
        base_url = None if runtime is None else runtime.ollama_base_url
        chat_model = build_chat_model(
            settings,
            provider=provider,
            model=model,
            base_url=base_url,
        )
        return build_tool_augmented_ask(
            settings,
            chat_model=chat_model,
            vector_store=vector_store,
            prompt_repository=prompt_repository,
        )

    return factory


SettingsDep = Annotated[Settings, Depends(get_settings)]
RuntimeSettingsDep = Annotated[GetRuntimeSettings, Depends(get_runtime_settings)]
ProbeOllamaStatusDep = Annotated[ProbeOllamaStatus, Depends(get_probe_ollama_status)]
AskFactoryDep = Annotated[AskFactory, Depends(get_ask_factory)]
