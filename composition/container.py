"""Composition root: the only place that constructs infrastructure."""

import importlib.util
import logging
import re
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path
from typing import NoReturn

from application.ask_knowledge import AskKnowledge
from application.ask_service import AskService
from application.contracts import (
    ConnectorSyncResponse,
    ConnectorSyncStatus,
    IngestRequest,
    IngestResponse,
)
from application.errors import (
    ApplicationValidationError,
    ConfigurationError,
    GoogleDriveNotConnectedError,
    GoogleDriveReauthorizationRequiredError,
    GoogleDriveSelectionRequiredError,
    InputRejectedError,
)
from application.ingest_knowledge import IngestFailure, IngestKnowledge
from application.invoke_tool import InvokeTool
from application.manage_documents import (
    DocumentManagementError,
    ManageUploadedDocuments,
    PartialCreateFailure,
    PartialDeleteFailure,
    PartialReplaceFailure,
    UnknownDocumentError,
)
from application.retrieve_knowledge import RetrieveKnowledge
from application.rewrite_and_retrieve import RewriteAndRetrieveKnowledge
from application.runtime_settings import (
    GetRuntimeSettings,
    ProbeOllamaStatus,
    RuntimeConstraints,
    RuntimeSettingsDefaults,
)
from application.sync_connector import SyncConnectorDocuments
from composition.errors import (
    ConnectorSyncError,
    DocumentContentError,
    DocumentOperationError,
    DocumentUploadError,
    GoogleDriveConnectorError,
    KnowledgeLoadError,
    PartialDocumentOperationError,
    UnknownUploadedDocumentError,
)
from composition.correlated_ask import CorrelatedAsk
from composition.logging_config import configure_logging
from composition.recording_chat import RecordingChatModel
from composition.software_delivery_chat import (
    OpaqueInvoke,
    PackSoftwareDeliveryChat,
)
from composition.software_delivery_tools import software_delivery_tools_enabled
from composition.tool_augmented_ask import GroundedAsk, ToolAugmentedAsk
from composition.tool_registry import (
    SUPPORTED_DOMAIN_TOOL_PACKS,
    enabled_domain_tool_packs,
    build_tool_registry,
)
from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    DomainValidationError,
    VectorStoreError,
)
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    ScoredChunk,
    SourceDocument,
    SourceReference,
    SourceType,
    UploadPayload,
)
from domain.ports import (
    ChatModel,
    DocumentCatalog,
    EmbeddingModel,
    KnowledgeConnector,
    PromptRepository,
    VectorStore,
)
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_catalog import SqlDocumentCatalog
from infrastructure.config import Settings, load_settings
from infrastructure.documents.uploaded_files import (
    SUPPORTED_SUFFIXES,
    DocumentExtractionError,
    UnreadableDocumentError,
    UploadedFileExtractor,
    extract_document,
    unsupported_document_type_detail,
)
from infrastructure.embeddings.openrouter import (
    EmbeddingConfigError,
    OpenRouterEmbeddings,
)
from infrastructure.knowledge.corpus import CorpusLoadError, load_knowledge_corpus
from infrastructure.llm.ollama import OllamaChat, OllamaConfigError
from infrastructure.llm.ollama import probe_ollama as _probe_ollama
from infrastructure.llm.openrouter import ChatConfigError, OpenRouterChat
from infrastructure.llm.query_rewrite import (
    OpenRouterQueryRewriter,
    QueryRewriteConfigError,
)
from infrastructure.prompts.markdown_repository import MarkdownPromptRepository
from infrastructure.lexical.bm25 import Bm25LexicalIndex
from infrastructure.vectorstore.chroma import ChromaStoreError, ChromaVectorStore
from infrastructure.vectorstore.dual_write import DualWriteVectorStore

SUPPORTED_UPLOAD_SUFFIXES: frozenset[str] = SUPPORTED_SUFFIXES

# Re-export so presentation adapters share one unsupported-type sentence.
unsupported_upload_type_detail = unsupported_document_type_detail

logger = logging.getLogger(__name__)



def _build_openrouter(
    settings: Settings, model: str | None, base_url: str | None
) -> ChatModel:
    config = settings.openrouter
    if model:
        config = replace(config, model=model)
    try:
        return OpenRouterChat(config)
    except ChatConfigError as exc:
        raise ConfigurationError(str(exc)) from exc


def _build_ollama(
    settings: Settings, model: str | None, base_url: str | None
) -> ChatModel:
    config = settings.ollama
    if model:
        config = replace(config, model=model)
    if base_url:
        config = replace(config, base_url=base_url)
    try:
        return OllamaChat(config)
    except OllamaConfigError as exc:
        raise ConfigurationError(str(exc)) from exc


_CHAT_MODELS: Mapping[str, Callable[[Settings, str | None, str | None], ChatModel]] = {
    "openrouter": _build_openrouter,
    "ollama": _build_ollama,
}


def available_providers() -> tuple[str, ...]:
    """The provider keys the composition root knows how to build."""
    return tuple(_CHAT_MODELS)


def build_runtime_settings(settings: Settings) -> GetRuntimeSettings:
    """Wire :class:`GetRuntimeSettings` from env Settings + available providers."""
    return GetRuntimeSettings(
        providers=available_providers(),
        defaults=RuntimeSettingsDefaults(
            provider=settings.provider,
            openrouter_models=tuple(settings.openrouter.models),
            openrouter_default_model=settings.openrouter.model,
            ollama_default_base_url=settings.ollama.base_url,
            ollama_default_model=settings.ollama.model,
            enabled_packs=enabled_domain_tool_packs(settings),
            constraints=RuntimeConstraints(
                max_input_length=settings.max_input_length,
                max_upload_bytes=settings.max_upload_bytes,
                supported_upload_suffixes=tuple(sorted(SUPPORTED_UPLOAD_SUFFIXES)),
            ),
        ),
    )


def build_probe_ollama_status(settings: Settings) -> ProbeOllamaStatus:
    """Wire :class:`ProbeOllamaStatus` to the infrastructure Ollama probe."""

    def _probe(base_url: str) -> dict:
        return probe_ollama(settings, base_url)

    return ProbeOllamaStatus(probe=_probe)


def load_runtime_settings() -> Settings:
    """Load environment settings for presentation and other composition callers.

    Wraps ``infrastructure.config.load_settings`` so presentation never imports
    infrastructure. Expected parse failures become ``ConfigurationError``.
    Also applies ``LOG_LEVEL`` via :func:`composition.logging_config.configure_logging`.

    Returns:
        Settings: Frozen runtime configuration for composition factories.

    Raises:
        ConfigurationError: If environment values fail known config validation.
    """
    configure_logging()
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
    chroma = ChromaVectorStore(settings.chroma)
    if not settings.retrieval.hybrid_enabled:
        return chroma
    if settings.retrieval.hybrid_alpha == 0.0:
        # Vector-only hybrid endpoint: no BM25 hydrate.
        return chroma
    lexical = Bm25LexicalIndex()
    lexical.upsert(chroma.list_embedded_chunks())
    return DualWriteVectorStore(chroma, lexical)


def build_ingest_knowledge(
    settings: Settings, *, vector_store: VectorStore | None = None
) -> IngestKnowledge:
    """Wire the ingest use case from the loaded settings.

    Only the embedding adapter's own configuration failure is mapped to a typed
    `ConfigurationError`. Vector-store failures keep `ChromaStoreError`: a
    missing credential and an unreadable collection are different problems, and
    relabelling the latter would send a caller looking in the wrong place.

    Pure, like `build_vector_store`: a fresh instance per call, so no open
    SQLite handle is retained across callers. A caller that already holds a
    store passes it in rather than opening a second client on the same
    collection.

    Raises:
        ConfigurationError: The embedding credentials are missing or unusable.
    """
    try:
        embedding_model = build_embedding_model(settings)
    except EmbeddingConfigError as exc:
        raise ConfigurationError(str(exc)) from exc
    if vector_store is None:
        vector_store = build_vector_store(settings)
    return IngestKnowledge(
        embedding_model,
        vector_store,
        chunk_size=settings.chunking.chunk_size,
        chunk_overlap=settings.chunking.chunk_overlap,
    )


def build_retrieve_knowledge(
    settings: Settings, *, vector_store: VectorStore | None = None
) -> RetrieveKnowledge:
    """Wire the retrieve use case from the loaded settings.

    Only the embedding adapter's own configuration failure is mapped to a typed
    `ConfigurationError`. Vector-store failures keep `ChromaStoreError`.

    Pure, like `build_ingest_knowledge`: a fresh instance per call. A caller
    that already holds a store passes it in rather than opening a second client
    on the same collection.

    When hybrid alpha is ``1``, no embedding adapter is constructed. When hybrid
    alpha is ``0``, BM25 is not required on the retrieve path.

    Raises:
        ConfigurationError: The embedding credentials are missing or unusable.
    """
    hybrid = settings.retrieval.hybrid_enabled
    alpha = settings.retrieval.hybrid_alpha
    needs_embedding = (not hybrid) or alpha < 1.0
    needs_lexical = hybrid and alpha > 0.0

    embedding_model = None
    if needs_embedding:
        try:
            embedding_model = build_embedding_model(settings)
        except EmbeddingConfigError as exc:
            raise ConfigurationError(str(exc)) from exc

    if vector_store is None:
        vector_store = build_vector_store(settings)

    lexical_index = None
    if needs_lexical:
        if not isinstance(vector_store, DualWriteVectorStore):
            raise ConfigurationError(
                "hybrid search with hybrid_alpha > 0 requires DualWriteVectorStore "
                "from build_vector_store; got "
                f"{type(vector_store).__name__}"
            )
        lexical_index = vector_store.lexical

    return RetrieveKnowledge(
        embedding_model,
        vector_store if needs_embedding else None,
        max_input_length=settings.max_input_length,
        hybrid_enabled=hybrid,
        lexical_index=lexical_index,
        hybrid_alpha=alpha,
        vector_score_floor=(
            settings.retrieval.relevance_threshold if hybrid and alpha < 1.0 else None
        ),
    )


def build_rewrite_and_retrieve_knowledge(
    settings: Settings, *, vector_store: VectorStore | None = None
) -> RewriteAndRetrieveKnowledge:
    """Wire rewrite-then-retrieve from the loaded settings.

    Maps adapter construction failures to ``ConfigurationError``:
    ``QueryRewriteConfigError`` for the rewriter and ``EmbeddingConfigError``
    for the retrieve path. Operational rewrite failures stay
    ``QueryRewriteFailure`` from the use case.

    Pure: a fresh instance per call. Pass an existing ``vector_store`` to share
    one client with ingest or plain retrieve.

    Raises:
        ConfigurationError: Rewrite or embedding credentials are missing.
    """
    try:
        rewriter = OpenRouterQueryRewriter(settings.openrouter)
    except QueryRewriteConfigError as exc:
        raise ConfigurationError(str(exc)) from exc
    retrieve = build_retrieve_knowledge(settings, vector_store=vector_store)
    return RewriteAndRetrieveKnowledge(
        rewriter,
        retrieve,
        max_input_length=settings.max_input_length,
    )


def reindex_filter_metadata(settings: Settings) -> int:
    """Promote stored ``extra`` keys so metadata filters work on legacy records.

    Opens the configured Chroma collection directly (not via ``build_vector_store``)
    and rewrites every record's metadata without re-embedding. Safe to run
    repeatedly. Hybrid/BM25 hydration is intentionally skipped: reindex is
    Chroma-specific and does not need a lexical index.

    Returns:
        The number of records rewritten.

    Raises:
        ChromaStoreError: The adapter could not read or rewrite the collection.
    """
    store = ChromaVectorStore(settings.chroma)
    return store.reindex_filter_metadata()


def _log_partial_create(error: PartialCreateFailure) -> None:
    """Record that a create half-landed, using only non-sensitive fields.

    Deliberately not ``logger.exception``. The chain behind this failure runs
    through adapter and vendor errors, and their text routinely carries the
    thing that broke: an API key echoed in a 401 body, a request header, an
    absolute catalog path, a slice of the uploaded document. A log file
    outlives the request and is read by more people than the screen was, so
    none of it is written here.

    What survives is what a reader can act on: which operation, that it landed
    partially, and which two exception classes were involved. The values stay
    on the exception — ``ingest_error`` and ``__cause__`` — for a debugger
    attached in-process, and go no further.
    """
    ingest_error = error.ingest_error
    logger.error(
        "operation=document_create outcome=partial_failure "
        "ingest_error=%s catalog_error=%s vector_mutation_started=%s",
        type(ingest_error).__name__,
        type(error.__cause__).__name__,
        getattr(ingest_error, "vector_mutation_started", None),
    )


def _upload_error_from_ingest_failure(
    settings: Settings, error: IngestFailure
) -> DocumentUploadError:
    """Translate an ingest failure into the message the UI should show.

    A store that was built with a different embedding size reports a vendor
    string nobody can act on, so it is replaced with the one instruction that
    fixes it. Every other cause keeps its own text.
    """
    cause = error.__cause__
    if not isinstance(cause, ChromaStoreError):
        return DocumentUploadError(str(error))
    message = str(cause)
    if "dimension" in message.lower():
        message = (
            "The knowledge store was built with a different embedding size "
            "than the current model. Delete the Chroma data directory "
            f"({settings.chroma.persist_path}) and ingest again."
        )
    return DocumentUploadError(message)


def ingest_uploaded_document(
    settings: Settings, path: Path, *, source_id: str
) -> IngestResponse:
    """Extract one uploaded file and ingest it through ``IngestKnowledge``.

    Owns extraction-to-ingestion wiring so presentation never imports the
    document adapter. Temporary-file lifecycle stays in presentation.

    Args:
        settings (Settings): Runtime settings for the ingest factory.
        path (Path): Local file whose suffix is already presentation-validated.
        source_id (str): Caller-supplied source identity.

    Returns:
        IngestResponse: Accepted IDs and chunk count from the use case.

    Raises:
        DocumentUploadError: Extraction failed (blank identity, unsupported
            type, or unreadable content), or the vector store rejected the
            write (for example an embedding-dimension mismatch).
        ConfigurationError: Embedding credentials are missing or unusable.
        ApplicationValidationError: The ingest request is invalid.
    """
    try:
        document = extract_document(path, source_id=source_id)
    except DomainValidationError as error:
        raise DocumentUploadError(str(error)) from error
    except DocumentExtractionError as error:
        raise DocumentUploadError(str(error)) from error

    use_case = build_ingest_knowledge(settings)
    try:
        return use_case.execute(IngestRequest(documents=(document,)))
    except IngestFailure as error:
        raise _upload_error_from_ingest_failure(settings, error) from error


def build_document_catalog(settings: Settings) -> DocumentCatalog:
    """Build the workspace-bound SQL catalog adapter.

    Args:
        settings (Settings): Runtime catalog configuration with a validated
            ``sql_path`` and ``workspace_id``.

    Returns:
        DocumentCatalog: ``SqlDocumentCatalog`` bound to the configured workspace.

    Raises:
        DocumentOperationError: The SQLite file or schema is unusable.
    """
    catalog = settings.document_catalog
    try:
        return SqlDocumentCatalog(catalog.sql_path, catalog.workspace_id)
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error
    except OSError as error:
        raise DocumentOperationError(str(error)) from error


def _resolve_catalog(
    settings: Settings,
    *,
    catalog: DocumentCatalog | None,
    catalog_factory: Callable[[], DocumentCatalog] | None,
) -> DocumentCatalog:
    if catalog is not None:
        return catalog
    if catalog_factory is not None:
        return catalog_factory()
    return build_document_catalog(settings)


_DRIVE_CONFIG_MESSAGE = "Google Drive connector configuration is invalid."
_DRIVE_SYNC_MESSAGE = "The Google Drive connector sync failed."
_DRIVE_REQUEST_MESSAGE = "The Google Drive request failed."
_DRIVE_CLIENT_MISSING_MESSAGE = (
    "Google Drive client is not installed; run uv sync --extra google-drive."
)
_DRIVE_ITEM_ID = re.compile(r"^(root|[A-Za-z0-9_-]{1,128})$")
_DRIVE_SELECTION_ID = re.compile(r"^(?!root$)[A-Za-z0-9_-]{1,128}$")
_DRIVE_ITEM_NAME_MAX = 256
_DRIVE_QUERY_MAX = 200
_DRIVE_SELECTION_VALIDATE_WORKERS = 16
_DRIVE_VALIDATION_POOL = ThreadPoolExecutor(
    max_workers=_DRIVE_SELECTION_VALIDATE_WORKERS,
    thread_name_prefix="drive-validate",
)
_SELECTION_INACCESSIBLE_DETAIL = "A selected Drive item is not accessible."
_SELECTION_KIND_DETAIL = "A selected Drive item does not match the requested type."


@dataclass(frozen=True, slots=True)
class GoogleDriveLastSync:
    """Last HTTP OAuth sync counts persisted with the user grant."""

    synced_at: str
    new_count: int
    updated_count: int
    unchanged_count: int
    failed_count: int


@dataclass(frozen=True, slots=True)
class GoogleDriveBrowseItem:
    """Presentation-safe Drive picker row. Identity is ``id``, never ``name``."""

    id: str
    name: str
    kind: str
    mime_type: str | None
    supported: bool
    modified_at: str | None


@dataclass(frozen=True, slots=True)
class GoogleDriveBrowsePage:
    """One picker page plus an opaque continuation token."""

    items: tuple[GoogleDriveBrowseItem, ...]
    next_page_token: str | None


@dataclass(frozen=True, slots=True)
class GoogleDriveSelectedItem:
    """Saved sync root: stable Drive ID plus a display name."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class GoogleDriveSelection:
    """Saved folder and exact-file roots for the connected grant."""

    folders: tuple[GoogleDriveSelectedItem, ...]
    files: tuple[GoogleDriveSelectedItem, ...]


@dataclass(frozen=True, slots=True)
class GoogleDriveStatus:
    """Drive SA presence, extra availability, and user OAuth connection.

    Args:
        configured (bool): Folder ID and service-account path are both set (CLI).
        available (bool): ``googleapiclient`` is importable.
        connected (bool): A user OAuth refresh token is stored.
        oauth_ready (bool): OAuth client ID, secret, and redirect URI are set.
        account_email (str | None): Display email from Drive about.get.
        document_count (int): Ready catalog rows with ``source_type=google_drive``.
        folder_count (int | None): Selected folder count when connected.
        last_sync (GoogleDriveLastSync | None): Last HTTP sync summary.
        reauthorization_required (bool): Stored refresh token was rejected.
        setup_required (bool): Unused; empty selection is still connected.
        connection_state (str): disconnected, ready, or
            reauthorization_required.
        sync_scope (str | None): Presentation summary such as ``2 folders + 1 file``.
    """

    configured: bool
    available: bool
    connected: bool = False
    oauth_ready: bool = False
    account_email: str | None = None
    document_count: int = 0
    folder_count: int | None = None
    last_sync: GoogleDriveLastSync | None = None
    reauthorization_required: bool = False
    setup_required: bool = False
    connection_state: str = "disconnected"
    sync_scope: str | None = None


def _oauth_ready(settings: Settings) -> bool:
    oauth = settings.google_oauth
    return bool(oauth.client_id and oauth.client_secret and oauth.redirect_uri)


def _connection_store(settings: Settings):
    from infrastructure.connectors.google_oauth import GoogleOAuthConnectionStore

    return GoogleOAuthConnectionStore(settings.google_oauth.token_path)


def _state_store(settings: Settings):
    from infrastructure.connectors.google_oauth import GoogleOAuthStateStore

    return GoogleOAuthStateStore(
        settings.google_oauth.state_path,
        ttl_seconds=settings.google_oauth.state_ttl_seconds,
    )


def _hub_redirect(settings: Settings, *, result: str) -> str:
    base = settings.google_oauth.frontend_redirect
    if base is None:
        origin = (
            settings.http.cors_origins[0]
            if settings.http.cors_origins
            else "http://localhost:3000"
        )
        base = f"{origin.rstrip('/')}/documents"
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}drive={result}"


def google_drive_status(
    settings: Settings,
    *,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
) -> GoogleDriveStatus:
    """Report SA flags plus user OAuth connection metadata.

    Does not import the Google client or load the service-account JSON.
    Catalog I/O failures degrade ``document_count`` to ``0``.

    Args:
        settings (Settings): Loaded environment settings.
        catalog (DocumentCatalog | None): Injected catalog for tests.
        catalog_factory (Callable[[], DocumentCatalog] | None): Lazy catalog
            builder used after the connection is known.

    Returns:
        GoogleDriveStatus: Presentation-safe flags and connection metadata.
    """
    drive = settings.google_drive
    configured = (
        drive.folder_id is not None and drive.service_account_file is not None
    )
    available = importlib.util.find_spec("googleapiclient") is not None
    connection = _connection_store(settings).load()
    last_sync = None
    if (
        connection is not None
        and connection.last_synced_at is not None
        and connection.last_sync_new is not None
        and connection.last_sync_updated is not None
        and connection.last_sync_unchanged is not None
        and connection.last_sync_failed is not None
    ):
        last_sync = GoogleDriveLastSync(
            synced_at=connection.last_synced_at,
            new_count=connection.last_sync_new,
            updated_count=connection.last_sync_updated,
            unchanged_count=connection.last_sync_unchanged,
            failed_count=connection.last_sync_failed,
        )
    reauthorization_required = (
        False if connection is None else connection.reauthorization_required
    )
    if connection is None:
        connection_state = "disconnected"
    elif reauthorization_required:
        connection_state = "reauthorization_required"
    else:
        connection_state = "ready"
    return GoogleDriveStatus(
        configured=configured,
        available=available,
        connected=connection is not None,
        oauth_ready=_oauth_ready(settings),
        account_email=(
            None
            if connection is None or connection.account_email_unverified
            else connection.account_email
        ),
        document_count=_drive_document_count(
            settings,
            connection=connection,
            catalog=catalog,
            catalog_factory=catalog_factory,
        ),
        folder_count=None if connection is None else len(connection.folders),
        last_sync=last_sync,
        reauthorization_required=reauthorization_required,
        setup_required=False,
        connection_state=connection_state,
        sync_scope=None if connection is None else _sync_scope_label(connection),
    )


def _drive_document_count(
    settings: Settings,
    *,
    connection,
    catalog: DocumentCatalog | None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
) -> int:
    if connection is None:
        return 0
    try:
        working = _resolve_catalog(
            settings, catalog=catalog, catalog_factory=catalog_factory
        )
        return working.count(
            source_type=SourceType.GOOGLE_DRIVE,
            status=CatalogStatus.READY,
        )
    except (
        CatalogError,
        ConfigurationError,
        DocumentOperationError,
        OSError,
        ValueError,
    ):
        logger.warning("Drive document count unavailable", exc_info=True)
        return 0


def _sync_scope_label(connection) -> str | None:
    folders = len(connection.folders)
    files = len(connection.files)
    if folders == 0 and files == 0:
        return None
    parts: list[str] = []
    if folders:
        parts.append(f"{folders} folder" + ("" if folders == 1 else "s"))
    if files:
        parts.append(f"{files} file" + ("" if files == 1 else "s"))
    return " + ".join(parts)


def start_google_drive_oauth(
    settings: Settings,
    *,
    state_store=None,
) -> str:
    """Issue CSRF state and return Google's authorization URL.

    When the OAuth client is missing, return the Hub URL with ``drive=unconfigured``
    so a browser GET never lands on a JSON problem page.

    Args:
        settings (Settings): Loaded environment settings.
        state_store: Injected state store for tests.

    Returns:
        str: Google authorization URL, or the Knowledge Hub error redirect.
    """
    if not _oauth_ready(settings):
        return _hub_redirect(settings, result="unconfigured")
    from infrastructure.connectors.google_oauth import authorization_url

    store = state_store if state_store is not None else _state_store(settings)
    state = store.issue()
    return authorization_url(settings.google_oauth, state=state)


def complete_google_drive_oauth(
    settings: Settings,
    *,
    state: str | None,
    code: str | None,
    error: str | None,
    state_store=None,
    connection_store=None,
    gateway=None,
) -> str:
    """Validate callback query params, persist the grant, return the Hub URL.

    Args:
        settings (Settings): Loaded environment settings.
        state (str | None): CSRF token from Google.
        code (str | None): Authorization code from Google.
        error (str | None): Provider error such as ``access_denied``.
        state_store: Injected state store for tests.
        connection_store: Injected connection store for tests.
        gateway: Injected Google token gateway for tests.

    Returns:
        str: Knowledge Hub URL with a non-sensitive ``drive=`` result.
    """
    if error == "access_denied":
        return _hub_redirect(settings, result="denied")
    store = state_store if state_store is not None else _state_store(settings)
    if not store.consume(state):
        return _hub_redirect(settings, result="invalid_state")
    if error or not code:
        return _hub_redirect(settings, result="error")
    if not _oauth_ready(settings):
        return _hub_redirect(settings, result="error")
    from infrastructure.connectors.google_oauth import (
        GoogleOAuthConnection,
        GoogleOAuthError,
        HttpGoogleOAuthGateway,
    )

    oauth_gateway = gateway if gateway is not None else HttpGoogleOAuthGateway(
        settings.google_oauth
    )
    tokens_store = (
        connection_store if connection_store is not None else _connection_store(settings)
    )
    try:
        grant = oauth_gateway.exchange_code(code)
        email = oauth_gateway.fetch_account_email(grant.access_token)

        def _next(existing):
            probe_failed = email is None
            keep_scope = (
                existing is not None
                and not probe_failed
                and existing.account_email == email
            )
            return GoogleOAuthConnection(
                refresh_token=grant.refresh_token,
                access_token=grant.access_token,
                account_email=(
                    existing.account_email
                    if probe_failed and existing is not None
                    else email
                ),
                last_synced_at=None if not keep_scope else existing.last_synced_at,
                last_sync_new=None if not keep_scope else existing.last_sync_new,
                last_sync_updated=None if not keep_scope else existing.last_sync_updated,
                last_sync_unchanged=None if not keep_scope else existing.last_sync_unchanged,
                last_sync_failed=None if not keep_scope else existing.last_sync_failed,
                reauthorization_required=False,
                folders=() if not keep_scope else existing.folders,
                files=() if not keep_scope else existing.files,
                account_email_unverified=probe_failed,
            )

        tokens_store.mutate(_next)
    except GoogleOAuthError:
        return _hub_redirect(settings, result="error")
    return _hub_redirect(settings, result="connected")


def disconnect_google_drive_oauth(
    settings: Settings,
    *,
    connection_store=None,
    gateway=None,
) -> None:
    """Revoke the stored refresh token and delete the local grant.

    Indexed Drive catalog rows are left in place.

    Args:
        settings (Settings): Loaded environment settings.
        connection_store: Injected connection store for tests.
        gateway: Injected Google token gateway for tests.

    Raises:
        GoogleDriveNotConnectedError: No stored grant.
    """
    tokens_store = (
        connection_store if connection_store is not None else _connection_store(settings)
    )
    connection = tokens_store.load()
    if connection is None:
        raise GoogleDriveNotConnectedError("Google Drive is not connected")
    from infrastructure.connectors.google_oauth import HttpGoogleOAuthGateway

    oauth_gateway = gateway if gateway is not None else HttpGoogleOAuthGateway(
        settings.google_oauth
    )
    oauth_gateway.revoke(connection.refresh_token)
    tokens_store.clear()


def _require_drive_grant(settings: Settings, *, connection_store=None):
    tokens_store = (
        connection_store if connection_store is not None else _connection_store(settings)
    )
    connection = tokens_store.load()
    if connection is None:
        raise GoogleDriveNotConnectedError("Google Drive is not connected")
    if connection.reauthorization_required:
        raise GoogleDriveReauthorizationRequiredError(
            "Google Drive authorization was revoked"
        )
    return tokens_store, connection


def _mark_reauth(tokens_store, error: BaseException) -> NoReturn:
    tokens_store.mutate(
        lambda current: None
        if current is None
        else replace(current, reauthorization_required=True)
    )
    raise GoogleDriveReauthorizationRequiredError(
        "Google Drive authorization was revoked"
    ) from error


def browse_google_drive_items(
    settings: Settings,
    *,
    parent_id: str | None = None,
    kind: str = "folders",
    query: str | None = None,
    page_token: str | None = None,
    connection_store=None,
    files=None,
) -> GoogleDriveBrowsePage:
    """List Drive folders or files for the content picker.

    Args:
        settings (Settings): Loaded environment settings.
        parent_id (str | None): Folder to list. Defaults to My Drive (``root``).
            Ignored when ``query`` is set.
        kind (str): ``folders`` or ``files``.
        query (str | None): Optional name search.
        page_token (str | None): Opaque continuation token.
        connection_store: Injected grant store for tests.
        files: Injected Drive files resource for tests.

    Returns:
        GoogleDriveBrowsePage: Presentation-safe rows and optional next token.

    Raises:
        GoogleDriveNotConnectedError: No stored grant.
        GoogleDriveReauthorizationRequiredError: Stored grant was rejected.
        InputRejectedError: ``parent_id``, ``kind``, or ``query`` is invalid.
        GoogleDriveConnectorError: Listing failed at the Google boundary.
    """
    if kind not in {"folders", "files"}:
        raise InputRejectedError("kind must be folders or files.")
    resolved_parent = "root" if parent_id is None or not parent_id.strip() else parent_id.strip()
    if not _DRIVE_ITEM_ID.fullmatch(resolved_parent):
        raise InputRejectedError("parent_id must be a Drive folder ID.")
    stripped_query = None if query is None else query.strip()
    if stripped_query == "":
        stripped_query = None
    if stripped_query is not None and len(stripped_query) > _DRIVE_QUERY_MAX:
        raise InputRejectedError("query is too long.")
    if page_token is not None and (not page_token.strip() or len(page_token) > 1024):
        raise InputRejectedError("page_token is invalid.")
    tokens_store, connection = _require_drive_grant(
        settings, connection_store=connection_store
    )
    try:
        connector = build_google_drive_oauth_connector(
            settings,
            refresh_token=connection.refresh_token,
            files=files,
        )
        page = connector.list_items(
            parent_id=resolved_parent,
            kind=kind,
            query=stripped_query,
            page_token=None if page_token is None else page_token.strip(),
        )
    except ConnectorAuthError as error:
        _mark_reauth(tokens_store, error)
    except ConnectorError as error:
        raise GoogleDriveConnectorError(_DRIVE_REQUEST_MESSAGE) from error
    return GoogleDriveBrowsePage(
        items=tuple(
            GoogleDriveBrowseItem(
                id=item.id,
                name=item.name,
                kind=item.kind,
                mime_type=item.mime_type,
                supported=item.supported,
                modified_at=item.modified_at,
            )
            for item in page.items
        ),
        next_page_token=page.next_page_token,
    )


def get_google_drive_selection(
    settings: Settings,
    *,
    connection_store=None,
) -> GoogleDriveSelection:
    """Return the saved folder and file roots (IDs and display names only).

    Args:
        settings (Settings): Loaded environment settings.
        connection_store: Injected grant store for tests.

    Returns:
        GoogleDriveSelection: Saved roots. Empty when setup is still required.

    Raises:
        GoogleDriveNotConnectedError: No stored grant.
        GoogleDriveReauthorizationRequiredError: Stored grant was rejected.
    """
    _tokens_store, connection = _require_drive_grant(
        settings, connection_store=connection_store
    )
    return GoogleDriveSelection(
        folders=tuple(
            GoogleDriveSelectedItem(id=item.id, name=item.name)
            for item in connection.folders
        ),
        files=tuple(
            GoogleDriveSelectedItem(id=item.id, name=item.name)
            for item in connection.files
        ),
    )


def put_google_drive_selection(
    settings: Settings,
    *,
    folders: Sequence[GoogleDriveSelectedItem],
    files: Sequence[GoogleDriveSelectedItem],
    connection_store=None,
    connector_factory=None,
) -> GoogleDriveSelection:
    """Validate access and atomically replace the saved Drive selection.

    Args:
        settings (Settings): Loaded environment settings.
        folders (Sequence[GoogleDriveSelectedItem]): Folder roots by Drive ID.
        files (Sequence[GoogleDriveSelectedItem]): Exact file IDs.
        connection_store: Injected grant store for tests.
        connector_factory: Injected ``get_item`` factory for tests.

    Returns:
        GoogleDriveSelection: The persisted roots.

    Raises:
        GoogleDriveNotConnectedError: No stored grant.
        GoogleDriveReauthorizationRequiredError: Stored grant was rejected.
        InputRejectedError: Duplicate, inaccessible, or mistyped items.
        GoogleDriveConnectorError: Validation failed at the Google boundary.
    """
    folder_items = _dedupe_selected(folders)
    file_items = _dedupe_selected(files)
    folder_ids = {item.id for item in folder_items}
    if folder_ids & {item.id for item in file_items}:
        raise InputRejectedError(_SELECTION_KIND_DETAIL)
    tokens_store, connection = _require_drive_grant(
        settings, connection_store=connection_store
    )
    try:
        resolved_folders, resolved_files = _validate_selection_items(
            settings,
            refresh_token=connection.refresh_token,
            folder_items=folder_items,
            file_items=file_items,
            connector_factory=connector_factory,
        )
    except ConnectorAuthError as error:
        _mark_reauth(tokens_store, error)
    except ConnectorError as error:
        raise InputRejectedError(_SELECTION_INACCESSIBLE_DETAIL) from error
    from infrastructure.connectors.google_oauth import GoogleDriveSelectedItem as StoredItem

    def _apply(current):
        if current is None:
            raise GoogleDriveNotConnectedError("Google Drive is not connected")
        if current.reauthorization_required:
            raise GoogleDriveReauthorizationRequiredError(
                "Google Drive authorization was revoked"
            )
        return replace(
            current,
            folders=tuple(
                StoredItem(id=item.id, name=item.name) for item in resolved_folders
            ),
            files=tuple(
                StoredItem(id=item.id, name=item.name) for item in resolved_files
            ),
        )

    tokens_store.mutate(_apply)
    return GoogleDriveSelection(folders=resolved_folders, files=resolved_files)


def _dedupe_selected(
    items: Sequence[GoogleDriveSelectedItem],
) -> tuple[GoogleDriveSelectedItem, ...]:
    seen: set[str] = set()
    unique: list[GoogleDriveSelectedItem] = []
    for item in items:
        item_id = item.id.strip()
        name = item.name.strip()
        if not _DRIVE_SELECTION_ID.fullmatch(item_id):
            raise InputRejectedError("A selected Drive ID is invalid.")
        if not name:
            raise InputRejectedError("A selected Drive name is missing.")
        if item_id in seen:
            continue
        seen.add(item_id)
        unique.append(GoogleDriveSelectedItem(id=item_id, name=name))
    return tuple(unique)


def _clamped_drive_name(name: str) -> str:
    stripped = name.strip()
    return stripped[:_DRIVE_ITEM_NAME_MAX]


def _validate_selection_items(
    settings: Settings,
    *,
    refresh_token: str,
    folder_items: Sequence[GoogleDriveSelectedItem],
    file_items: Sequence[GoogleDriveSelectedItem],
    connector_factory=None,
) -> tuple[tuple[GoogleDriveSelectedItem, ...], tuple[GoogleDriveSelectedItem, ...]]:
    jobs = [(item, "folder") for item in folder_items] + [
        (item, "file") for item in file_items
    ]
    if not jobs:
        return (), ()

    def default_factory():
        return build_google_drive_oauth_connector(
            settings, refresh_token=refresh_token
        )

    factory = default_factory if connector_factory is None else connector_factory
    probe_item, probe_kind = jobs[0]
    try:
        _validate_selected_item(factory(), probe_item, expected_kind=probe_kind)
    except ConnectorAuthError:
        raise
    except (InputRejectedError, ConnectorError):
        pass

    local = threading.local()

    def _run(item: GoogleDriveSelectedItem, kind: str) -> GoogleDriveSelectedItem:
        connector = getattr(local, "connector", None)
        if connector is None:
            connector = factory()
            local.connector = connector
        return _validate_selected_item(connector, item, expected_kind=kind)

    workers = min(_DRIVE_SELECTION_VALIDATE_WORKERS, len(jobs))
    resolved: dict[int, GoogleDriveSelectedItem] = {}
    next_job = 0
    in_flight: dict[Future[GoogleDriveSelectedItem], int] = {}

    def _fill() -> None:
        nonlocal next_job
        while next_job < len(jobs) and len(in_flight) < workers:
            item, kind = jobs[next_job]
            in_flight[_DRIVE_VALIDATION_POOL.submit(_run, item, kind)] = next_job
            next_job += 1

    _fill()
    try:
        while in_flight:
            done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            errors: list[tuple[int, BaseException]] = []
            for future in done:
                index = in_flight.pop(future)
                try:
                    resolved[index] = future.result()
                except BaseException as error:
                    errors.append((index, error))
            if errors:
                raise _preferred_validation_error(errors)
            _fill()
    finally:
        _log_finished_validation_jobs(in_flight)
    folder_count = len(folder_items)
    return (
        tuple(resolved[index] for index in range(folder_count)),
        tuple(resolved[index] for index in range(folder_count, len(jobs))),
    )


def _preferred_validation_error(
    errors: Sequence[tuple[int, BaseException]],
) -> BaseException:
    for _index, error in errors:
        if isinstance(error, ConnectorAuthError):
            return error
    return min(errors, key=lambda pair: pair[0])[1]


def _log_finished_validation_jobs(
    futures: Iterable[Future[GoogleDriveSelectedItem]],
) -> None:
    for future in futures:
        if not future.done() or future.cancelled():
            continue
        error = future.exception()
        if error is None:
            continue
        if isinstance(error, InputRejectedError):
            logger.debug("Drive selection validation job rejected: %s", error)
            continue
        logger.warning(
            "Drive selection validation job failed",
            exc_info=error,
        )


def _validate_selected_item(
    connector,
    item: GoogleDriveSelectedItem,
    *,
    expected_kind: str,
) -> GoogleDriveSelectedItem:
    remote = connector.get_item(item.id)
    if remote.kind != expected_kind:
        raise InputRejectedError(_SELECTION_KIND_DETAIL)
    if expected_kind == "file" and not remote.supported:
        raise InputRejectedError(_SELECTION_KIND_DETAIL)
    name = _clamped_drive_name(remote.name) or _clamped_drive_name(item.name)
    return GoogleDriveSelectedItem(id=remote.id, name=name)


def build_google_drive_oauth_connector(
    settings: Settings,
    *,
    refresh_token: str,
    folder_ids: Sequence[str] = (),
    file_ids: Sequence[str] = (),
    recursive: bool = True,
    files=None,
):
    """Build a Drive connector from a stored user refresh token.

    Args:
        settings (Settings): Loaded environment settings.
        refresh_token (str): Stored user refresh token.
        folder_ids (Sequence[str]): Saved folder roots. Recursive when True.
        file_ids (Sequence[str]): Exact Drive file IDs.
        recursive (bool): Walk folder descendants. Hub sync uses True.
        files: Injected Drive ``files`` resource for tests.

    Returns:
        KnowledgeConnector: Drive adapter bound to the saved selection.

    Raises:
        ConfigurationError: Client extra or OAuth client is unusable.
        GoogleDriveReauthorizationRequiredError: Refresh token was rejected.
    """
    from infrastructure.config import GoogleDriveSettings
    from infrastructure.connectors.google_oauth import (
        GoogleOAuthError,
        build_oauth_drive_files,
    )

    try:
        from infrastructure.connectors.google_drive import (
            GoogleDriveConfigError,
            GoogleDriveConnector,
        )
    except ImportError as error:
        raise ConfigurationError(_DRIVE_CLIENT_MISSING_MESSAGE) from error
    try:
        drive_files = (
            files
            if files is not None
            else build_oauth_drive_files(
                settings.google_oauth, refresh_token=refresh_token
            )
        )
        return GoogleDriveConnector(
            GoogleDriveSettings(
                service_account_file=None,
                folder_id=None,
                page_size=settings.google_drive.page_size,
            ),
            max_upload_bytes=settings.max_upload_bytes,
            files=drive_files,
            folder_ids=tuple(folder_ids),
            file_ids=tuple(file_ids),
            recursive=recursive,
        )
    except (GoogleDriveConfigError, GoogleOAuthError) as error:
        raise ConfigurationError(_DRIVE_CONFIG_MESSAGE) from error


def sync_google_drive_oauth(
    settings: Settings,
    *,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
    connection_store=None,
) -> ConnectorSyncResponse:
    """Synchronize Drive using the stored user OAuth grant.

    Args:
        settings (Settings): Loaded environment settings.
        catalog (DocumentCatalog | None): Injected catalog for tests.
        catalog_factory (Callable[[], DocumentCatalog] | None): Lazy catalog
            builder used after not-connected / reauth / selection guards.
        vector_store (VectorStore | None): Shared store for the run.
        vector_store_factory (Callable[[], VectorStore] | None): Lazy store
            builder used after not-connected / reauth / selection guards.
        connection_store: Injected connection store for tests.

    Returns:
        ConnectorSyncResponse: Per-document outcomes in listing order.

    Raises:
        GoogleDriveNotConnectedError: No stored grant.
        GoogleDriveReauthorizationRequiredError: Refresh token was rejected.
        GoogleDriveSelectionRequiredError: The grant has no saved Drive roots.
        ConnectorSyncError: Listing, auth, catalog, or store infrastructure failed.
    """
    from datetime import datetime, timezone

    tokens_store, connection = _require_drive_grant(
        settings, connection_store=connection_store
    )
    if not connection.folders and not connection.files:
        raise GoogleDriveSelectionRequiredError(
            "Google Drive sync scope is not selected"
        )
    try:
        working_catalog = _resolve_catalog(
            settings, catalog=catalog, catalog_factory=catalog_factory
        )
        before = {
            row.reference.source_id
            for row in working_catalog.all()
            if row.reference.source_type == SourceType.GOOGLE_DRIVE
        }
        connector = build_google_drive_oauth_connector(
            settings,
            refresh_token=connection.refresh_token,
            folder_ids=tuple(item.id for item in connection.folders),
            file_ids=tuple(item.id for item in connection.files),
            recursive=True,
        )
        result = sync_google_drive(
            settings,
            connector=connector,
            catalog=working_catalog,
            vector_store=vector_store,
            vector_store_factory=vector_store_factory,
        )
    except ConnectorSyncError as error:
        if isinstance(error.__cause__, ConnectorAuthError):
            _mark_reauth(tokens_store, error)
        raise
    new_count = sum(
        1
        for outcome in result.outcomes
        if outcome.status is ConnectorSyncStatus.INGESTED
        and outcome.source_id not in before
    )
    updated_count = sum(
        1
        for outcome in result.outcomes
        if outcome.status is ConnectorSyncStatus.INGESTED
        and outcome.source_id in before
    )
    synced_at = datetime.now(timezone.utc).isoformat()
    tokens_store.mutate(
        lambda current: None
        if current is None
        else replace(
            current,
            last_synced_at=synced_at,
            last_sync_new=new_count,
            last_sync_updated=updated_count,
            last_sync_unchanged=result.skipped_count,
            last_sync_failed=result.failed_count,
        )
    )
    return result


def build_google_drive_connector(settings: Settings) -> KnowledgeConnector:
    """Build the Google Drive connector from runtime settings.

    Args:
        settings (Settings): Loaded environment settings.

    Returns:
        KnowledgeConnector: Drive adapter bound to the configured folder.

    Raises:
        ConfigurationError: Drive folder, credentials, or client extra is missing
            or unusable.
    """
    try:
        from infrastructure.connectors.google_drive import (
            GoogleDriveConfigError,
            GoogleDriveConnector,
        )
    except ImportError as error:
        raise ConfigurationError(_DRIVE_CLIENT_MISSING_MESSAGE) from error
    try:
        return GoogleDriveConnector(
            settings.google_drive,
            max_upload_bytes=settings.max_upload_bytes,
        )
    except GoogleDriveConfigError as error:
        raise ConfigurationError(_DRIVE_CONFIG_MESSAGE) from error


def sync_google_drive(
    settings: Settings,
    *,
    connector: KnowledgeConnector | None = None,
    catalog: DocumentCatalog | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
) -> ConnectorSyncResponse:
    """Synchronize the configured Drive folder into the knowledge base.

    One vector store is cached for the run. The ingest pipeline is constructed
    only when a listed document needs ingestion.

    Args:
        settings (Settings): Loaded environment settings.
        connector (KnowledgeConnector | None): Injected connector for tests.
        catalog (DocumentCatalog | None): Injected catalog for tests.
        vector_store (VectorStore | None): Shared store for the run, if already built.
        vector_store_factory (Callable[[], VectorStore] | None): Lazy store builder
            used by ingest instead of constructing the store up front.

    Returns:
        ConnectorSyncResponse: Per-document outcomes in listing order.

    Raises:
        ConfigurationError: Connector or embedding configuration is invalid.
        ConnectorSyncError: Listing, auth, catalog, or store infrastructure failed.
    """
    try:
        if connector is None:
            connector = build_google_drive_connector(settings)
        if catalog is None:
            catalog = build_document_catalog(settings)
        shared_store = vector_store

        def get_store() -> VectorStore:
            nonlocal shared_store
            if shared_store is None:
                if vector_store_factory is not None:
                    shared_store = vector_store_factory()
                else:
                    shared_store = build_vector_store(settings)
            return shared_store

        return SyncConnectorDocuments(
            connector=connector,
            catalog=catalog,
            ingest_factory=lambda: build_ingest_knowledge(
                settings,
                vector_store=get_store(),
            ),
        ).execute()
    except ConnectorError as error:
        raise ConnectorSyncError(_DRIVE_SYNC_MESSAGE) from error
    except CatalogError as error:
        raise ConnectorSyncError(_DRIVE_SYNC_MESSAGE) from error
    except VectorStoreError as error:
        raise ConnectorSyncError(_DRIVE_SYNC_MESSAGE) from error


def build_document_extractor() -> UploadedFileExtractor:
    """Build the upload-payload extractor adapter."""
    return UploadedFileExtractor()


def build_manage_uploaded_documents(
    settings: Settings,
    *,
    catalog: DocumentCatalog | None = None,
    vector_store: VectorStore | None = None,
) -> ManageUploadedDocuments:
    """Wire create/replace/delete/list for uploaded documents.

    The store and the ingest pipeline are passed as factories the use case calls
    only when it needs them. Listing then costs one JSON read — no Chroma client
    and no embedding credentials — which matters because the documents list
    path should stay cheap on every request, and because `list` and `delete`
    never embed anything.
    Each operation opens at most one store, and both paths open it through the
    same factory, so ingest and delete cannot drift onto different collections.

    Pass ``vector_store`` to reuse a cached DualWrite/Chroma client (hybrid BM25
    stays in sync with uploads). When omitted, each mutating call builds a fresh
    store via ``build_vector_store``.
    """
    shared = vector_store

    def _vector_store() -> VectorStore:
        nonlocal shared
        if shared is None:
            shared = build_vector_store(settings)
        return shared

    def _ingest() -> IngestKnowledge:
        return build_ingest_knowledge(settings, vector_store=_vector_store())

    return ManageUploadedDocuments(
        catalog=catalog if catalog is not None else build_document_catalog(settings),
        extractor=build_document_extractor(),
        ingest_factory=_ingest,
        vector_store_factory=_vector_store,
        max_upload_bytes=settings.max_upload_bytes,
    )


def list_uploaded_documents(
    settings: Settings, *, catalog: DocumentCatalog | None = None
) -> tuple[CatalogDocument, ...]:
    """Return every uploaded-document catalog row."""
    try:
        return tuple(
            build_manage_uploaded_documents(settings, catalog=catalog).list()
        )
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error


def create_uploaded_document(
    settings: Settings,
    payload: UploadPayload,
    *,
    catalog: DocumentCatalog | None = None,
    vector_store: VectorStore | None = None,
) -> CatalogDocument:
    """Create a new uploaded document with a system-managed source ID.

    Raises:
        PartialDocumentOperationError: The upload failed and its catalog status
            could not be written, so a stale row may be visible.
        DocumentUploadError: The file could not be extracted or ingested.
        DocumentOperationError: The catalog could not be read or written.
    """
    try:
        return build_manage_uploaded_documents(
            settings, catalog=catalog, vector_store=vector_store
        ).create(payload)
    except UnreadableDocumentError as error:
        raise DocumentContentError(str(error)) from error
    except DocumentExtractionError as error:
        raise DocumentUploadError(str(error)) from error
    except DomainValidationError as error:
        raise DocumentUploadError(str(error)) from error
    except PartialCreateFailure as error:
        _log_partial_create(error)
        raise PartialDocumentOperationError(
            str(error), operation="create"
        ) from error
    except IngestFailure as error:
        raise _upload_error_from_ingest_failure(settings, error) from error
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error
    except DocumentManagementError as error:
        raise DocumentOperationError(str(error)) from error
    except (ApplicationValidationError, ConfigurationError):
        raise
    except Exception as error:
        raise DocumentUploadError(str(error)) from error


def replace_uploaded_document(
    settings: Settings,
    reference: SourceReference,
    payload: UploadPayload,
    *,
    catalog: DocumentCatalog | None = None,
    vector_store: VectorStore | None = None,
) -> CatalogDocument:
    """Replace an existing uploaded document under the same source ID.

    Raises:
        PartialDocumentOperationError: Chunks or the catalog row were left
            mid-replace, so a retry is genuinely required.
        UnknownUploadedDocumentError: ``reference`` is not in the catalog.
        DocumentOperationError: The replace stopped without mutating anything.
        DocumentContentError: The replacement file has no extractable text.
        DocumentUploadError: The replacement file could not be extracted.
    """
    try:
        ops = build_manage_uploaded_documents(
            settings, catalog=catalog, vector_store=vector_store
        )
        return ops.replace(reference, payload)
    except UnknownDocumentError as error:
        raise UnknownUploadedDocumentError(str(error)) from error
    except UnreadableDocumentError as error:
        raise DocumentContentError(str(error)) from error
    except DocumentExtractionError as error:
        raise DocumentUploadError(str(error)) from error
    except DomainValidationError as error:
        raise DocumentUploadError(str(error)) from error
    except PartialReplaceFailure as error:
        raise PartialDocumentOperationError(
            str(error), operation="replace"
        ) from error
    except IngestFailure as error:
        # A failure before the first `delete_source` left the previous version
        # stored and its catalog row restored: nothing for the user to retry.
        if error.vector_mutation_started:
            raise PartialDocumentOperationError(
                str(error), operation="replace"
            ) from error
        raise DocumentOperationError(str(error)) from error
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error
    except DocumentManagementError as error:
        raise DocumentOperationError(str(error)) from error
    except (ApplicationValidationError, ConfigurationError):
        raise
    except Exception as error:
        raise DocumentUploadError(str(error)) from error


def delete_uploaded_document(
    settings: Settings,
    reference: SourceReference,
    *,
    catalog: DocumentCatalog | None = None,
    vector_store: VectorStore | None = None,
) -> None:
    """Delete vector chunks then the catalog row for ``reference``.

    Google Drive rows are also removed from the saved Drive file selection so
    the next sync does not bring them back.

    Raises:
        PartialDocumentOperationError: The chunks are gone but the catalog row
            remains, so a retry is genuinely required.
        DocumentOperationError: The delete stopped before removing anything.
    """
    ops = build_manage_uploaded_documents(
        settings, catalog=catalog, vector_store=vector_store
    )
    row = ops.resolve(reference.source_id)
    target = row.reference if row is not None else reference
    try:
        ops.delete(target)
    except PartialDeleteFailure as error:
        raise PartialDocumentOperationError(
            str(error), operation="delete"
        ) from error
    except DocumentManagementError as error:
        raise DocumentOperationError(str(error)) from error
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error
    if (
        row is not None
        and row.reference.source_type == SourceType.GOOGLE_DRIVE
    ):
        _after_google_drive_document_deleted(settings, row.reference.source_id)


def _after_google_drive_document_deleted(settings: Settings, file_id: str) -> None:
    """Drop ``file_id`` from saved file roots after a Drive catalog delete."""
    _connection_store(settings).mutate(
        lambda current: None
        if current is None
        else replace(
            current,
            files=tuple(item for item in current.files if item.id != file_id),
        )
    )


def build_prompt_repository(settings: Settings) -> PromptRepository:
    return MarkdownPromptRepository(
        settings.prompts.pack_paths,
        default_key=settings.prompts.default_key,
    )


def build_ask_service(chat_model: ChatModel) -> AskService:
    return AskService(chat_model)


def build_ask_knowledge(
    settings: Settings,
    *,
    chat_model: ChatModel | None = None,
    vector_store: VectorStore | None = None,
    prompt_repository: PromptRepository | None = None,
) -> AskKnowledge:
    """Wire grounded ask from rewrite/retrieve, the ask service, and prompts.

    Generation is wrapped in `AskService` rather than handed to `AskKnowledge`
    raw, so the domain settings allowlist stays in one place.
    """
    if chat_model is None:
        chat_model = build_chat_model(settings)
    if prompt_repository is None:
        prompt_repository = build_prompt_repository(settings)
    rewrite_and_retrieve = build_rewrite_and_retrieve_knowledge(
        settings, vector_store=vector_store
    )
    return AskKnowledge(
        rewrite_and_retrieve,
        build_ask_service(chat_model),
        prompt_repository,
        default_retrieval_limit=settings.retrieval.limit,
        relevance_threshold=settings.retrieval.relevance_threshold,
        max_input_length=settings.max_input_length,
        keep_retrieved_hits=settings.retrieval.hybrid_enabled,
    )


def build_invoke_tool(
    settings: Settings, *, chat_model: ChatModel | None = None
) -> InvokeTool:
    """Wire opaque ``InvokeTool`` to the configured domain tool registry.

    Args:
        settings (Settings): Runtime settings including enabled tool packs.
        chat_model (ChatModel | None): Required when ``software-delivery`` is
            enabled; injected only, never constructed here.

    Returns:
        InvokeTool: Generic lookup-and-run use case.
    """
    return InvokeTool(build_tool_registry(settings, chat_model=chat_model))


def build_opaque_invoke(
    settings: Settings, *, chat_model: ChatModel | None = None
) -> OpaqueInvoke:
    """Return the tool boundary as a plain callable, results still opaque.

    Exposed so a caller can wrap it — the chat path records one
    ``InvokeToolResponse`` per call — without rebuilding the registry itself.
    """
    invoke_tool = build_invoke_tool(settings, chat_model=chat_model)

    def invoke(tool_name: str, arguments: Mapping[str, object]) -> str:
        from application.contracts import InvokeToolRequest

        return invoke_tool.execute(
            InvokeToolRequest(tool_name, arguments)
        ).result

    return invoke


def build_orchestrate_software_delivery(
    settings: Settings,
    *,
    chat_model: ChatModel,
    invoke: OpaqueInvoke | None = None,
) -> object:
    """Wire Software Delivery orchestration when the pack is enabled.

    Imports pack orchestration only for configured pack IDs so disabled packs
    are not loaded at import time.

    Args:
        settings (Settings): Runtime settings including enabled tool packs.
        chat_model (ChatModel): Shared chat adapter for generate-test-cases.
        invoke (OpaqueInvoke | None): Optional replacement for the tool boundary,
            so a caller can observe the chain without a second orchestrator.
            Defaults to the registry-backed callable.

    Returns:
        OrchestrateSoftwareDelivery: Pack orchestration use case.

    Raises:
        ConfigurationError: Pack disabled or orchestrator cannot be built.
    """
    if "software-delivery" not in settings.domain_tools.enabled_packs:
        raise ConfigurationError(
            "software-delivery pack must be enabled to build orchestration"
        )
    if invoke is None:
        invoke = build_opaque_invoke(settings, chat_model=chat_model)

    import importlib

    registration = importlib.import_module(
        "packs.software_delivery.registration"
    )
    return registration.build_orchestrator(invoke=invoke)


def _relevant_retrieve(
    settings: Settings, *, vector_store: VectorStore | None = None
) -> Callable[[str], tuple[ScoredChunk, ...]]:
    """Bind filter-less cross-source retrieval with the relevance threshold.

    The threshold belongs here rather than in a pack: top-k on a non-empty store
    returns ``k`` chunks for *any* query, so without it "the store returned rows"
    would be mistaken for "we have evidence" — the reasoning
    ``AskKnowledge._relevant`` documents. There is no ``metadata_filters``
    channel, which is what makes narrowing to one source kind structurally
    impossible for the caller.

    In Hybrid mode, raw cosine eligibility is applied inside retrieve before
    fusion; this binder keeps already-qualified hits and does not re-apply the
    raw cosine threshold to fused ranking scores.
    """
    rewrite_and_retrieve = build_rewrite_and_retrieve_knowledge(
        settings, vector_store=vector_store
    )
    threshold = settings.retrieval.relevance_threshold
    limit = settings.retrieval.limit
    keep_retrieved = settings.retrieval.hybrid_enabled

    def retrieve(query: str) -> tuple[ScoredChunk, ...]:
        from application.contracts import RetrieveRequest

        response = rewrite_and_retrieve.execute(
            RetrieveRequest(query=query, retrieval_limit=limit)
        )
        if keep_retrieved:
            return tuple(response.hits)
        return tuple(hit for hit in response.hits if hit.score >= threshold)

    return retrieve


def build_tool_augmented_ask(
    settings: Settings,
    *,
    chat_model: ChatModel | None = None,
    vector_store: VectorStore | None = None,
    prompt_repository: PromptRepository | None = None,
) -> GroundedAsk:
    """Wire grounded ask, adding chat-time tool selection when a pack is enabled.

    Always wraps the result in :class:`CorrelatedAsk` so every chat turn — pack
    enabled or not — shares one ``request_id`` across ask / retrieve / tools.

    With no pack enabled the inner ask is ``build_ask_knowledge``. The gate reads
    settings only, so a disabled pack is never imported.

    When ``vector_store`` is omitted and a software-delivery pack is enabled,
    one store is built and shared by grounded ask and pack retrieve so hybrid
    BM25 hydration runs at most once. FastAPI should inject a
    process-cached store so uploads mutate the same DualWrite index.

    Args:
        settings (Settings): Runtime settings including enabled tool packs.
        chat_model (ChatModel | None): Shared chat adapter; built when absent.
        vector_store (VectorStore | None): Optional shared vector store client.
        prompt_repository (PromptRepository | None): Optional shared prompts.

    Returns:
        GroundedAsk: ``CorrelatedAsk`` around ``AskKnowledge`` or
        ``ToolAugmentedAsk``.
    """
    if chat_model is None:
        chat_model = build_chat_model(settings)
    if not software_delivery_tools_enabled(settings):
        ask = build_ask_knowledge(
            settings,
            chat_model=chat_model,
            vector_store=vector_store,
            prompt_repository=prompt_repository,
        )
        return CorrelatedAsk(ask)

    # Pack path uses grounded ask and a second retrieve; share one store so
    # hybrid BM25 hydration runs at most once when the caller did not inject.
    if vector_store is None:
        vector_store = build_vector_store(settings)
    ask = build_ask_knowledge(
        settings,
        chat_model=chat_model,
        vector_store=vector_store,
        prompt_repository=prompt_repository,
    )

    import importlib

    registration = importlib.import_module("packs.software_delivery.registration")
    # Tools invoke ChatModel through the opaque boundary; record safe RunMeta so
    # latency/tokens can reach ToolRunOutcome.run without entering tool JSON.
    model_calls = RecordingChatModel(chat_model)

    def orchestrate(
        *,
        target: str,
        hits: Sequence[ScoredChunk],
        generate_tests: bool,
        output_style: str,
        invoke: OpaqueInvoke,
    ):
        from packs.software_delivery.evidence_bundle import evidence_bundle_from_hits
        from packs.software_delivery.orchestration_contracts import (
            OrchestrateSoftwareDeliveryRequest,
        )
        from packs.software_delivery.orchestration_policy import SoftwareDeliveryIntent

        # Pass the recording wrapper so any future path that builds tools from
        # chat_model (when invoke is absent) still contributes to RunMeta.
        orchestrator = build_orchestrate_software_delivery(
            settings, chat_model=model_calls, invoke=invoke
        )
        intent = (
            SoftwareDeliveryIntent.RISK_SCORE_GENERATE_EXPORT
            if generate_tests
            else SoftwareDeliveryIntent.RISK_SCORE
        )
        return orchestrator.execute(
            OrchestrateSoftwareDeliveryRequest(
                intent=intent,
                target=target,
                evidence=evidence_bundle_from_hits(hits),
                output_style=output_style,
            )
        )

    runner = PackSoftwareDeliveryChat(
        retrieve=_relevant_retrieve(settings, vector_store=vector_store),
        invoke=build_opaque_invoke(settings, chat_model=model_calls),
        orchestrate=orchestrate,
        model_calls=model_calls,
    )

    return CorrelatedAsk(
        ToolAugmentedAsk(
            ask,
            runner=runner,
            select=registration.build_chat_intent_selector(),
            pack_id="software-delivery",
        )
    )


def probe_ollama(settings: Settings, base_url: str) -> dict:
    """Reachability check, with the timeout taken from settings."""
    return _probe_ollama(base_url, settings.ollama.timeout)
