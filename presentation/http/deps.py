"""FastAPI dependencies for the HTTP presentation adapter."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Protocol

from fastapi import Depends

from application.contracts import ConnectorSyncResponse
from application.runtime_settings import GetRuntimeSettings, ProbeOllamaStatus
from composition import (
    SUPPORTED_UPLOAD_SUFFIXES,
    GoogleDriveBrowsePage,
    GoogleDriveSelection,
    GoogleDriveSelectedItem,
    GoogleDriveStatus,
    GroundedAsk,
    Settings,
    browse_google_drive_items,
    build_chat_model,
    build_document_catalog,
    build_prompt_repository,
    build_probe_ollama_status,
    build_runtime_settings,
    build_tool_augmented_ask,
    build_vector_store,
    create_uploaded_document,
    delete_uploaded_document,
    complete_google_drive_oauth,
    disconnect_google_drive_oauth,
    get_google_drive_selection,
    get_uploaded_document_content,
    google_drive_status,
    list_uploaded_document_chunks,
    list_uploaded_documents,
    load_runtime_settings,
    put_google_drive_selection,
    replace_uploaded_document,
    start_google_drive_oauth,
    sync_google_drive_oauth,
)
from domain.knowledge import (
    CatalogDocument,
    ChunkPage,
    SourceReference,
    UploadPayload,
)
from domain.ports import DocumentCatalog, PromptRepository, VectorStore
from presentation.http.schemas import ChatRuntimeRequest


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Resolve runtime settings once per process through composition.

    Process-cached settings load: avoids re-running ``configure_logging`` /
    ``load_dotenv(override=False)`` on every FastAPI request.
    """
    return load_runtime_settings()


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    """Process-cached vector store (hybrid BM25 hydrate once per process)."""
    return build_vector_store(get_settings())


@lru_cache(maxsize=1)
def get_document_catalog() -> DocumentCatalog:
    """Process-cached document catalog (one SQLite/JSON adapter per process)."""
    return build_document_catalog(get_settings())


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
            provider=provider,
            model=model,
            base_url=base_url,
        )

    return factory


class ListDocumentChunks(Protocol):
    """List stored chunks for one catalogued source reference."""

    def __call__(
        self,
        reference: SourceReference,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> ChunkPage: ...


@dataclass(frozen=True, slots=True)
class DocumentOperations:
    """The composition document seam, bound to this process's settings."""

    list: Callable[[], tuple[CatalogDocument, ...]]
    list_chunks: ListDocumentChunks
    create: Callable[[UploadPayload], CatalogDocument]
    replace: Callable[[SourceReference, UploadPayload], CatalogDocument]
    delete: Callable[[SourceReference], None]
    get_content: Callable[[str], tuple[CatalogDocument, UploadPayload]]
    supported_suffixes: frozenset[str]
    max_upload_bytes: int


def get_document_operations(
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentOperations:
    """Bind list/create/replace/delete to settings and a lazy vector store.

    The store is not built here — catalog ``list`` must work without embedding
    credentials. Mutating operations and ``list_chunks`` resolve the process-wide
    ``get_vector_store`` cache on first use (DualWrite forwards chunk listing to
    Chroma without BM25). The process-cached catalog is resolved on first use so
    a missing catalog still maps to ``DocumentOperationError`` instead of failing
    dependency resolution.
    """

    def create(payload: UploadPayload) -> CatalogDocument:
        return create_uploaded_document(
            settings,
            payload,
            catalog=get_document_catalog(),
            vector_store=get_vector_store(),
        )

    def replace(
        reference: SourceReference, payload: UploadPayload
    ) -> CatalogDocument:
        return replace_uploaded_document(
            settings,
            reference,
            payload,
            catalog=get_document_catalog(),
            vector_store=get_vector_store(),
        )

    def delete(reference: SourceReference) -> None:
        delete_uploaded_document(
            settings,
            reference,
            catalog=get_document_catalog(),
            vector_store=get_vector_store(),
        )

    def content(source_id: str) -> tuple[CatalogDocument, UploadPayload]:
        return get_uploaded_document_content(
            settings,
            source_id,
            catalog=get_document_catalog(),
        )

    def list_chunks(
        reference: SourceReference,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> ChunkPage:
        return list_uploaded_document_chunks(
            settings,
            reference,
            catalog=get_document_catalog(),
            vector_store=get_vector_store(),
            limit=limit,
            offset=offset,
        )

    return DocumentOperations(
        list=lambda: list_uploaded_documents(
            settings, catalog=get_document_catalog()
        ),
        list_chunks=list_chunks,
        create=create,
        replace=replace,
        delete=delete,
        get_content=content,
        supported_suffixes=SUPPORTED_UPLOAD_SUFFIXES,
        max_upload_bytes=settings.max_upload_bytes,
    )


def get_google_drive_status(
    settings: Annotated[Settings, Depends(get_settings)],
) -> GoogleDriveStatus:
    """Report Drive configuration presence and extra availability."""
    return google_drive_status(
        settings, catalog_factory=get_document_catalog
    )


def get_google_drive_sync(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Callable[[], ConnectorSyncResponse]:
    """Return a Drive sync callable that builds the vector store lazily.

    The store is not built here — unconfigured POST must 409 without embedding
    credentials. After the not-connected / reauth / selection guards,
    ``sync_google_drive_oauth`` reuses the process-cached DualWrite/BM25 store.
    """

    def sync() -> ConnectorSyncResponse:
        return sync_google_drive_oauth(
            settings,
            catalog_factory=get_document_catalog,
            vector_store_factory=get_vector_store,
        )

    return sync


def get_google_drive_oauth_start(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Callable[[], str]:
    """Return a callable that issues CSRF state and builds Google's auth URL."""

    def start() -> str:
        return start_google_drive_oauth(settings)

    return start


def get_google_drive_oauth_callback(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Callable[[str | None, str | None, str | None], str]:
    """Return a callable that completes the OAuth callback."""

    def complete(
        state: str | None, code: str | None, error: str | None
    ) -> str:
        return complete_google_drive_oauth(
            settings, state=state, code=code, error=error
        )

    return complete


def get_google_drive_disconnect(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Callable[[], None]:
    """Return a callable that revokes and deletes the stored user grant."""

    def disconnect() -> None:
        disconnect_google_drive_oauth(settings)

    return disconnect


def get_google_drive_browse(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Callable[..., GoogleDriveBrowsePage]:
    """Return a Drive picker listing callable bound to this process."""

    def browse(
        *,
        parent_id: str | None = None,
        kind: str = "folders",
        query: str | None = None,
        page_token: str | None = None,
    ) -> GoogleDriveBrowsePage:
        return browse_google_drive_items(
            settings,
            parent_id=parent_id,
            kind=kind,
            query=query,
            page_token=page_token,
        )

    return browse


def get_google_drive_selection_read(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Callable[[], GoogleDriveSelection]:
    """Return a callable that loads the saved Drive selection."""

    def load() -> GoogleDriveSelection:
        return get_google_drive_selection(settings)

    return load


def get_google_drive_selection_write(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Callable[..., GoogleDriveSelection]:
    """Return a callable that validates and replaces the saved Drive selection."""

    def save(
        *,
        folders: tuple[GoogleDriveSelectedItem, ...],
        files: tuple[GoogleDriveSelectedItem, ...],
    ) -> GoogleDriveSelection:
        return put_google_drive_selection(
            settings, folders=folders, files=files
        )

    return save


SettingsDep = Annotated[Settings, Depends(get_settings)]
RuntimeSettingsDep = Annotated[GetRuntimeSettings, Depends(get_runtime_settings)]
ProbeOllamaStatusDep = Annotated[ProbeOllamaStatus, Depends(get_probe_ollama_status)]
AskFactoryDep = Annotated[AskFactory, Depends(get_ask_factory)]
DocumentOperationsDep = Annotated[
    DocumentOperations, Depends(get_document_operations)
]
GoogleDriveStatusDep = Annotated[
    GoogleDriveStatus, Depends(get_google_drive_status)
]
GoogleDriveSyncDep = Annotated[
    Callable[[], ConnectorSyncResponse], Depends(get_google_drive_sync)
]
GoogleDriveOAuthStartDep = Annotated[
    Callable[[], str], Depends(get_google_drive_oauth_start)
]
GoogleDriveOAuthCallbackDep = Annotated[
    Callable[[str | None, str | None, str | None], str],
    Depends(get_google_drive_oauth_callback),
]
GoogleDriveDisconnectDep = Annotated[
    Callable[[], None], Depends(get_google_drive_disconnect)
]
GoogleDriveBrowseDep = Annotated[
    Callable[..., GoogleDriveBrowsePage], Depends(get_google_drive_browse)
]
GoogleDriveSelectionReadDep = Annotated[
    Callable[[], GoogleDriveSelection], Depends(get_google_drive_selection_read)
]
GoogleDriveSelectionWriteDep = Annotated[
    Callable[..., GoogleDriveSelection], Depends(get_google_drive_selection_write)
]
