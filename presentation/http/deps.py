"""FastAPI dependencies for the HTTP presentation adapter."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Protocol

from fastapi import Depends

from application.runtime_settings import GetRuntimeSettings, ProbeOllamaStatus
from composition import (
    SUPPORTED_UPLOAD_SUFFIXES,
    GroundedAsk,
    Settings,
    build_chat_model,
    build_prompt_repository,
    build_probe_ollama_status,
    build_runtime_settings,
    build_tool_augmented_ask,
    build_vector_store,
    create_uploaded_document,
    delete_uploaded_document,
    list_uploaded_documents,
    load_runtime_settings,
    replace_uploaded_document,
)
from domain.knowledge import CatalogDocument, SourceReference, UploadPayload
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


@dataclass(frozen=True, slots=True)
class DocumentOperations:
    """The composition document seam, bound to this process's settings."""

    list: Callable[[], tuple[CatalogDocument, ...]]
    create: Callable[[UploadPayload], CatalogDocument]
    replace: Callable[[SourceReference, UploadPayload], CatalogDocument]
    delete: Callable[[SourceReference], None]
    supported_suffixes: frozenset[str]
    max_upload_bytes: int


def get_document_operations(
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentOperations:
    """Bind list/create/replace/delete to settings and a lazy vector store.

    The store is not built here — ``list`` must work without embedding
    credentials. Mutating operations resolve it on first use via the
    process-wide ``get_vector_store`` cache.
    """

    def create(payload: UploadPayload) -> CatalogDocument:
        return create_uploaded_document(
            settings, payload, vector_store=get_vector_store()
        )

    def replace(
        reference: SourceReference, payload: UploadPayload
    ) -> CatalogDocument:
        return replace_uploaded_document(
            settings, reference, payload, vector_store=get_vector_store()
        )

    def delete(reference: SourceReference) -> None:
        delete_uploaded_document(
            settings, reference, vector_store=get_vector_store()
        )

    return DocumentOperations(
        list=lambda: list_uploaded_documents(settings),
        create=create,
        replace=replace,
        delete=delete,
        supported_suffixes=SUPPORTED_UPLOAD_SUFFIXES,
        max_upload_bytes=settings.max_upload_bytes,
    )


SettingsDep = Annotated[Settings, Depends(get_settings)]
RuntimeSettingsDep = Annotated[GetRuntimeSettings, Depends(get_runtime_settings)]
ProbeOllamaStatusDep = Annotated[ProbeOllamaStatus, Depends(get_probe_ollama_status)]
AskFactoryDep = Annotated[AskFactory, Depends(get_ask_factory)]
DocumentOperationsDep = Annotated[
    DocumentOperations, Depends(get_document_operations)
]
