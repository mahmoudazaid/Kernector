"""Composition root: the only place that constructs infrastructure."""

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from application.ask_knowledge import AskKnowledge
from application.ask_service import AskService
from application.errors import (
    ConfigurationError,
    MissingProviderCredentialsError,
    OllamaNotConfiguredError,
)
from application.ingest_knowledge import IngestKnowledge
from application.invoke_tool import InvokeTool
from application.retrieve_knowledge import RetrieveKnowledge
from application.rewrite_and_retrieve import RewriteAndRetrieveKnowledge
from application.runtime_settings import (
    GetRuntimeSettings,
    ProbeOllamaStatus,
    RuntimeConstraints,
    RuntimeSettingsDefaults,
)
from composition.errors import (
    DocumentOperationError,
    KnowledgeLoadError,
)
from composition.chat.clarification_context import ClarificationContextStore
from composition.chat.correlated_ask import CorrelatedAsk
from composition.logging_config import configure_logging
from composition.chat.recording_chat import RecordingChatModel
from composition.software_delivery.agent import build_agent_orchestrate
from composition.software_delivery.chat import (
    OpaqueInvoke,
    PackSoftwareDeliveryChat,
)
from composition.software_delivery.tools import software_delivery_tools_enabled
from composition.chat.tool_augmented_ask import (
    GroundedAsk,
    ToolAugmentedAsk,
    ToolRunner,
)
from composition.tools.registry import (
    enabled_domain_tool_packs,
    build_tool_registry,
)
from domain.knowledge import (
    ScoredChunk,
    SourceDocument,
)
from domain.ports import (
    ChatModel,
    DocumentCatalog,
    EmbeddingModel,
    PromptRepository,
    UploadBlobStore,
    VectorStore,
)
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_catalog import SqlDocumentCatalog
from infrastructure.catalog.workspace import WORKSPACE_ID_CONTRACT, parse_workspace_id
from infrastructure.config import (
    OllamaSettings,
    OpenRouterSettings,
    Settings,
    load_settings,
)
from infrastructure.documents.upload_blob_store import (
    FilesystemUploadBlobStore,
)
from infrastructure.documents.uploaded_files import (
    CONTENT_TYPE_BY_FORMAT,
    SUPPORTED_SUFFIXES,
    unsupported_document_type_detail,
)
from infrastructure.embeddings.openrouter import (
    EmbeddingConfigError,
    OpenRouterEmbeddings,
)
from infrastructure.knowledge.corpus import CorpusLoadError, load_knowledge_corpus
from infrastructure.llm.ollama import (
    OllamaBaseUrlMissingError,
    OllamaChat,
    OllamaConfigError,
    OllamaModelMissingError,
)
from infrastructure.llm.ollama import probe_ollama as _probe_ollama
from infrastructure.llm.openrouter import ChatConfigError, OpenRouterChat
from infrastructure.llm.query_rewrite import (
    OpenRouterQueryRewriter,
    QueryRewriteConfigError,
)
from infrastructure.prompts.markdown_repository import MarkdownPromptRepository
from infrastructure.lexical.bm25 import Bm25LexicalIndex
from infrastructure.vectorstore.chroma import ChromaVectorStore
from infrastructure.vectorstore.dual_write import DualWriteVectorStore

if TYPE_CHECKING:
    from composition.test_design.facade import TestDesignFacade

SUPPORTED_UPLOAD_SUFFIXES: frozenset[str] = SUPPORTED_SUFFIXES

# Re-export so presentation adapters share one unsupported-type sentence.
unsupported_upload_type_detail = unsupported_document_type_detail
# Same single source for preview/download Content-Type as upload suffixes.
UPLOAD_CONTENT_TYPE_BY_FORMAT: dict[str, str] = CONTENT_TYPE_BY_FORMAT

logger = logging.getLogger(__name__)


def _build_openrouter(
    settings: Settings, model: str | None, base_url: str | None
) -> ChatModel:
    del base_url  # OpenRouter ignores per-request base URL overrides.
    config = _openrouter_runtime_config(settings, model=model)
    try:
        return OpenRouterChat(config)
    except ChatConfigError as exc:
        raise MissingProviderCredentialsError(str(exc)) from exc


def _build_ollama(
    settings: Settings, model: str | None, base_url: str | None
) -> ChatModel:
    config = _ollama_runtime_config(settings, model=model, base_url=base_url)
    try:
        return OllamaChat(config)
    except OllamaBaseUrlMissingError as exc:
        raise OllamaNotConfiguredError(str(exc)) from exc
    except OllamaModelMissingError as exc:
        raise MissingProviderCredentialsError(str(exc)) from exc
    except OllamaConfigError as exc:
        # Future/unclassified Ollama construction failures: treat as credentials.
        raise MissingProviderCredentialsError(str(exc)) from exc


def _openrouter_runtime_config(
    settings: Settings, *, model: str | None
) -> OpenRouterSettings:
    config = settings.openrouter
    if model:
        config = replace(config, model=model)
    return config


def _ollama_runtime_config(
    settings: Settings, *, model: str | None, base_url: str | None
) -> OllamaSettings:
    config = settings.ollama
    if model:
        config = replace(config, model=model)
    if base_url:
        config = replace(config, base_url=base_url)
    return config


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


def build_chroma_vector_store(settings: Settings) -> ChromaVectorStore:
    """Return Chroma only (no BM25 hydrate). For chunk listing and similar reads."""
    return ChromaVectorStore(settings.chroma)


def build_vector_store(settings: Settings) -> VectorStore:
    chroma = build_chroma_vector_store(settings)
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


def _workspace_store_path(settings: Settings):
    from pathlib import Path

    store_path = Path("data/workspace_store/workspace.sqlite")
    if settings.document_catalog.sql_path is not None:
        store_path = (
            settings.document_catalog.sql_path.parent / "workspace_store.sqlite"
        )
    return store_path


def _response_feedback_path(settings: Settings):
    from pathlib import Path

    store_path = Path("data/feedback/response_feedback.sqlite")
    if settings.document_catalog.sql_path is not None:
        store_path = (
            settings.document_catalog.sql_path.parent / "response_feedback.sqlite"
        )
    return store_path


def build_response_feedback_repository(settings: Settings):
    """Build the workspace-bound SQLite response feedback repository."""
    from infrastructure.feedback.errors import FeedbackStoreError
    from infrastructure.feedback.sql_repository import SqlResponseFeedbackRepository

    workspace_id = _require_workspace_id(settings)
    try:
        return SqlResponseFeedbackRepository(
            _response_feedback_path(settings), workspace_id
        )
    except FeedbackStoreError as error:
        raise ConfigurationError(str(error)) from error
    except OSError as error:
        raise ConfigurationError(
            f"could not open response feedback store: {error}"
        ) from error


def build_submit_response_feedback(settings: Settings):
    """Build the submit-feedback use case for the configured workspace."""
    from application.submit_response_feedback import (
        NullRunProvenanceLookup,
        SubmitResponseFeedback,
    )

    repository = build_response_feedback_repository(settings)
    return SubmitResponseFeedback(
        repository=repository,
        provenance=NullRunProvenanceLookup(),
        workspace_id=_require_workspace_id(settings),
    )


def build_clear_response_feedback(settings: Settings):
    """Build the clear-feedback use case for the configured workspace."""
    from application.submit_response_feedback import ClearResponseFeedback

    return ClearResponseFeedback(
        repository=build_response_feedback_repository(settings)
    )


def build_get_response_feedback(settings: Settings):
    """Build the get-feedback use case for the configured workspace."""
    from application.submit_response_feedback import GetResponseFeedback

    return GetResponseFeedback(
        repository=build_response_feedback_repository(settings)
    )


def _require_workspace_id(settings: Settings) -> str:
    try:
        workspace_id = parse_workspace_id(settings.document_catalog.workspace_id)
    except ValueError as error:
        raise ConfigurationError(
            f"DOCUMENT_CATALOG_WORKSPACE_ID {error}"
        ) from error
    if workspace_id is None:
        raise ConfigurationError(
            f"DOCUMENT_CATALOG_WORKSPACE_ID is required; it {WORKSPACE_ID_CONTRACT}"
        )
    return workspace_id


def _agent_draft_repository(settings: Settings):
    from infrastructure.workspace_store.sql_store import VersionedWorkspaceStore
    from composition.test_design.store import VersionedTestCoverageDraftRepository

    return VersionedTestCoverageDraftRepository(
        VersionedWorkspaceStore(
            _workspace_store_path(settings), _require_workspace_id(settings)
        )
    )


def _agent_export_destination_repository(settings: Settings):
    from infrastructure.workspace_store.sql_store import VersionedWorkspaceStore
    from composition.drive_export.destination_store import (
        VersionedExportDestinationRepository,
    )

    return VersionedExportDestinationRepository(
        VersionedWorkspaceStore(
            _workspace_store_path(settings), _require_workspace_id(settings)
        )
    )


def build_test_design_facade(
    settings: Settings,
    *,
    connection_store=None,
    oauth_gateway=None,
    client_factory=None,
) -> "TestDesignFacade":
    """Wire the test-design HTTP facade (pack gated at call time)."""
    from composition.test_design.facade import TestDesignFacade

    workspace_id = _require_workspace_id(settings)
    store_path = _workspace_store_path(settings)
    return TestDesignFacade(
        settings=settings,
        store_path=store_path,
        workspace_id=workspace_id,
        sources=build_test_design_sources(
            settings,
            connection_store=connection_store,
            oauth_gateway=oauth_gateway,
            client_factory=client_factory,
        ),
    )


def build_test_design_sources(
    settings: Settings,
    *,
    connection_store=None,
    oauth_gateway=None,
    client_factory=None,
    jira_dc_state_store=None,
    jira_dc_client_factory=None,
    jira_dc_settings_provider=None,
):
    """Register the live sources Test Design may plan from.

    GitHub is always registered; Jira Data Center only when its mode is active
    (``JIRA_DC_BASE_URL`` or ``JIRA_DC_TOKEN`` set). Credentials are resolved
    lazily when a reader is requested, so building the registry never requires
    a grant or a network call.
    """
    from composition.test_design.github_source import build_github_test_design_source
    from composition.test_design.sources import (
        TestDesignSource,
        TestDesignSourceRegistry,
    )

    sources: list[TestDesignSource] = [
        build_github_test_design_source(
            settings,
            connection_store=connection_store,
            oauth_gateway=oauth_gateway,
            client_factory=client_factory,
        )
    ]
    dc = settings.jira_data_center
    if dc is not None:
        from composition.test_design.jira_data_center_source import (
            build_jira_data_center_test_design_source,
        )

        sources.append(
            build_jira_data_center_test_design_source(
                jira_dc_settings_provider or (lambda: dc),
                state_store=jira_dc_state_store,
                client_factory=jira_dc_client_factory,
            )
        )
    return TestDesignSourceRegistry(sources)


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


_RETIRED_CATALOG_ENV = (
    "DOCUMENT_CATALOG_BACKEND",
    "DOCUMENT_CATALOG_PATH",
)


def _reject_retired_catalog_env() -> None:
    """Fail when a non-blank retired catalog key is still configured."""
    for key in _RETIRED_CATALOG_ENV:
        value = os.getenv(key)
        if value is not None and value.strip():
            raise ConfigurationError(
                f"{key} is retired; use DOCUMENT_CATALOG_SQL_PATH and "
                "DOCUMENT_CATALOG_WORKSPACE_ID"
            )


def build_document_catalog(settings: Settings) -> DocumentCatalog:
    """Build the workspace-bound SQL catalog adapter.

    Args:
        settings (Settings): Runtime catalog configuration with a
            ``sql_path`` and optional ``workspace_id`` (validated here).

    Returns:
        DocumentCatalog: ``SqlDocumentCatalog`` bound to the configured workspace.

    Raises:
        ConfigurationError: ``DOCUMENT_CATALOG_SQL_PATH`` or
            ``DOCUMENT_CATALOG_WORKSPACE_ID`` is absent or invalid, or a retired
            catalog env key is still set.
        DocumentOperationError: The SQLite file or schema is unusable.
    """
    _reject_retired_catalog_env()
    catalog = settings.document_catalog
    if catalog.sql_path is None:
        raise ConfigurationError(
            "DOCUMENT_CATALOG_SQL_PATH is blank; unset it to use the "
            "data/catalog/catalog.sqlite default"
        )
    try:
        workspace_id = parse_workspace_id(catalog.workspace_id)
    except ValueError as error:
        raise ConfigurationError(
            f"DOCUMENT_CATALOG_WORKSPACE_ID {error}"
        ) from error
    if workspace_id is None:
        raise ConfigurationError(
            f"DOCUMENT_CATALOG_WORKSPACE_ID is required; it {WORKSPACE_ID_CONTRACT}"
        )
    try:
        return SqlDocumentCatalog(catalog.sql_path, workspace_id)
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error
    except OSError as error:
        raise DocumentOperationError(str(error)) from error


def build_upload_blob_store(settings: Settings) -> UploadBlobStore:
    """Build durable storage for original uploaded document payloads."""
    return FilesystemUploadBlobStore(settings.upload_blobs.root)


def resolve_catalog(
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


def lazy_vector_store(
    settings: Settings,
    *,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
) -> Callable[[], VectorStore]:
    """Memoize one store: ``vector_store`` wins; else factory; else build.

    When both ``vector_store`` and ``vector_store_factory`` are passed,
    ``vector_store`` wins and the factory is never called. Pass only the
    factory to defer opening until the first call.
    """
    shared_store = vector_store

    def get_store() -> VectorStore:
        nonlocal shared_store
        if shared_store is None:
            if vector_store_factory is not None:
                shared_store = vector_store_factory()
            else:
                shared_store = build_vector_store(settings)
        return shared_store

    return get_store


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
        chat_model (ChatModel | None): Optional; required only when a future
            LLM-backed pack tool needs it. Drive export does not use chat.

    Returns:
        InvokeTool: Generic lookup-and-run use case.
    """
    from composition.google_drive.connection import drive_oauth_ready

    export_render = None
    export_uploader = None
    if (
        "software-delivery" in settings.domain_tools.enabled_packs
        and drive_oauth_ready(settings)
    ):
        from composition.software_delivery.export import render_export_markdown
        from infrastructure.connectors.google_drive.artifact_uploader import (
            GoogleDriveArtifactUploader,
        )
        from infrastructure.connectors.google_drive.oauth import (
            GoogleOAuthConnectionStore,
        )

        export_render = render_export_markdown
        export_uploader = GoogleDriveArtifactUploader(
            oauth_settings=settings.google_oauth,
            connection_store=GoogleOAuthConnectionStore(
                settings.google_oauth.token_path
            ),
        )
    xray_importer, xray_load_draft = _xray_tool_collaborators(settings)
    return InvokeTool(
        build_tool_registry(
            settings,
            chat_model=chat_model,
            export_render=export_render,
            export_uploader=export_uploader,
            xray_importer=xray_importer,
            xray_load_draft=xray_load_draft,
        )
    )


def _xray_tool_collaborators(settings: Settings):
    """Return ``(importer, load_draft)`` for Xray export, or ``(None, None)``."""
    if (
        "software-delivery" not in settings.domain_tools.enabled_packs
        or not settings.xray.configured
    ):
        return None, None
    try:
        _require_workspace_id(settings)
    except ConfigurationError as error:
        logger.warning("Xray test creation disabled: %s", error)
        return None, None
    from composition.xray_export.wiring import build_xray_importer

    importer = build_xray_importer(settings)
    if importer is None:
        return None, None

    def load_draft(draft_id: str):
        return _agent_draft_repository(settings).get(draft_id)

    return importer, load_draft

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


class _ToolsUnavailableRunner:
    """Tool runner for stacks with no live chat tool chain wired.

    The pack-disabled stack and the deterministic (non-agent) stack both land
    here: only the agent loop can run Drive export.
    """

    def run(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("domain tools are not enabled")


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
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    short_term_memory: object | None = None,
    client_source_locator: object | None = None,
    clarification_context_store: ClarificationContextStore | None = None,
) -> GroundedAsk:
    """Wire grounded ask with TurnRouter, AskGeneral, and pack workflow signals.

    Always wraps the result in :class:`CorrelatedAsk` so every chat turn — pack
    enabled or not — shares one ``request_id`` across ask / retrieve / tools.

    ``task_prompt`` short-circuits before the router. Pack workflow detection is
    injected as WorkflowSignals; handoffs/actions are built after a ready
    ``tool_workflow`` decision.

    Args:
        settings (Settings): Runtime settings including enabled tool packs.
        chat_model (ChatModel | None): Shared chat adapter; built when absent.
        vector_store (VectorStore | None): Optional shared vector store client.
        prompt_repository (PromptRepository | None): Optional shared prompts.
        provider (str | None): Per-request provider override (same as chat model).
        model (str | None): Per-request model override.
        base_url (str | None): Per-request Ollama base URL override.
        short_term_memory (object | None): Optional
            :class:`~composition.chat.short_term_memory.ShortTermMemoryRuntime`.
            When omitted and the agent loop is on, a fresh runtime is built for
            this stack (tests should inject a shared runtime for continuity).
        client_source_locator: Optional client Issue locator for Test Design
            handoff mismatch checks.
        clarification_context_store: Optional conversation-scoped prior
            clarification context store for follow-up workflow turns.

    Returns:
        GroundedAsk: ``CorrelatedAsk`` around ``ToolAugmentedAsk``.
    """
    from application.ask_general import AskGeneral
    from composition.chat.clarification_context import (
        InMemoryClarificationContextStore,
    )
    from composition.chat.workflow_signals import (
        build_drive_export_workflow_signal,
        build_test_design_workflow_signal,
        build_xray_export_workflow_signal,
    )

    if clarification_context_store is None:
        clarification_context_store = InMemoryClarificationContextStore()

    if chat_model is None:
        chat_model = build_chat_model(
            settings, provider=provider, model=model, base_url=base_url
        )
    ask_general = AskGeneral(
        build_ask_service(chat_model),
        max_input_length=settings.max_input_length,
    )

    if not software_delivery_tools_enabled(settings):
        ask = build_ask_knowledge(
            settings,
            chat_model=chat_model,
            vector_store=vector_store,
            prompt_repository=prompt_repository,
        )

        return CorrelatedAsk(
            ToolAugmentedAsk(
                ask,
                runner=_ToolsUnavailableRunner(),
                signals=(),
                ask_general=ask_general,
                clarification_context_store=clarification_context_store,
            )
        )

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

    drafts = None
    grounded_ask = None
    xray_export_enabled = False
    runner: ToolRunner = _ToolsUnavailableRunner()
    if settings.domain_tools.agent_loop:
        from application.ask_knowledge_with_agent import AskKnowledgeWithAgent
        from application.retrieval_citation_channel import RetrievalCitationChannel
        from application.retrieve_knowledge_tool import RetrieveKnowledgeTool
        from application.untrusted_text import agent_tool_system_prompt
        from composition.chat.short_term_memory import (
            ShortTermMemoryRuntime,
            build_short_term_memory_runtime,
        )

        runtime = short_term_memory
        if runtime is None:
            runtime = build_short_term_memory_runtime(settings)
        if not isinstance(runtime, ShortTermMemoryRuntime):
            raise TypeError("short_term_memory must be a ShortTermMemoryRuntime")
        try:
            drafts = _agent_draft_repository(settings)
            destinations = _agent_export_destination_repository(settings)
        except ConfigurationError as error:
            # Match short-term memory: missing/invalid workspace degrades so
            # /chat/ask stays available instead of 500.
            logger.warning(
                "Agent draft/destination stores disabled: %s", error
            )

            class _EmptyDrafts:
                def find_by_conversation_id(self, conversation_id: str):
                    del conversation_id
                    return None

            class _EmptyDestinations:
                def get(self, conversation_id: str):
                    del conversation_id
                    return None

            drafts = _EmptyDrafts()
            destinations = _EmptyDestinations()
        # Tools invoke ChatModel through the opaque boundary; record safe RunMeta
        # so latency/tokens reach ToolRunOutcome.run without entering tool JSON.
        # Accumulates ReAct model turns plus any tool ChatModel calls.
        model_calls = RecordingChatModel(chat_model, accumulate=True)
        citation_channel = RetrievalCitationChannel()
        retrieve_tool = RetrieveKnowledgeTool(
            build_rewrite_and_retrieve_knowledge(
                settings, vector_store=vector_store
            ),
            citation_channel,
            retrieval_limit=settings.retrieval.limit,
            max_input_length=settings.max_input_length,
            relevance_threshold=settings.retrieval.relevance_threshold,
            keep_retrieved_hits=settings.retrieval.hybrid_enabled,
        )
        tool_agent = runtime.bind_tool_agent(
            system_prompt=agent_tool_system_prompt(),
            model_factory=_software_delivery_agent_model_factory(
                settings,
                recorder=model_calls,
                provider=provider,
                model=model,
                base_url=base_url,
            ),
        )
        grounded_ask = AskKnowledgeWithAgent(
            tool_agent,
            retrieve_tool,
            citation_channel,
            max_input_length=settings.max_input_length,
        )
        prepare_xray = None
        if _xray_tool_collaborators(settings)[0] is not None:
            from composition.xray_export.prepare import prepare_xray_export_call

            xray_drafts = drafts
            project_key = settings.xray.project_key or ""
            xray_export_enabled = True

            def prepare_xray(conversation_id: str):
                return prepare_xray_export_call(
                    conversation_id=conversation_id,
                    drafts=xray_drafts,
                    project_key=project_key,
                )

        # Drive export stays retrieval-free: omit retrieve_tool here.
        # Pass retrieve_tool into build_agent_orchestrate only for evidence
        # multi-tool workflows that opt in.
        runner = PackSoftwareDeliveryChat(
            retrieve=_relevant_retrieve(settings, vector_store=vector_store),
            invoke=build_opaque_invoke(settings, chat_model=model_calls),
            orchestrate=build_agent_orchestrate(
                tool_agent,
                drafts=drafts,
                destinations=destinations,
                prepare_xray=prepare_xray,
            ),
            model_calls=model_calls,
            allow_empty_evidence=True,
            defer_retrieval=True,
            citation_channel=citation_channel,
        )

    from composition.test_design.facade import build_test_design_handoff_from_request

    test_design_sources = build_test_design_sources(settings)
    signals = (
        build_test_design_workflow_signal(enabled=True),
        build_drive_export_workflow_signal(
            export_enabled=settings.domain_tools.agent_loop,
            drafts=drafts,
        ),
        build_xray_export_workflow_signal(
            export_enabled=xray_export_enabled,
            drafts=drafts,
        ),
    )

    def build_handoff(request):
        return build_test_design_handoff_from_request(
            settings=settings,
            request=request,
            sources=test_design_sources,
            source_locator=client_source_locator,  # type: ignore[arg-type]
        )

    return CorrelatedAsk(
        ToolAugmentedAsk(
            ask,
            runner=runner,
            signals=signals,
            ask_general=ask_general,
            pack_id="software-delivery",
            build_test_design_handoff=build_handoff,
            clarification_context_store=clarification_context_store,
            grounded_ask=grounded_ask,
        )
    )


def _software_delivery_agent_model_factory(
    settings: Settings,
    *,
    recorder: RecordingChatModel | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
):
    """Return a LangChain chat model factory with ``bind_tools`` for the agent.

    Validates the full provider credential contract via the same ``_build_*``
    helpers as live chat (typed ``ConfigurationError`` subclasses), then builds
    a LangChain ``ChatOpenAI`` from the same resolved runtime config.

    Args:
        settings (Settings): Process settings for provider defaults.
        recorder (RecordingChatModel | None): Optional RunMeta accumulator.
        provider (str | None): Per-request provider override.
        model (str | None): Per-request model override.
        base_url (str | None): Per-request Ollama base URL override.

    Returns:
        Callable: Zero-arg factory producing an observing chat model with tools.
    """

    def factory(**_kwargs: object):
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr

        from domain.errors import ProviderError

        effective = provider or settings.provider
        builder = _CHAT_MODELS.get(effective)
        if builder is None:
            raise ValueError(
                f"Unknown provider {effective!r}. "
                f"Expected one of {sorted(_CHAT_MODELS)}."
            )
        # Validate via chat builders (discard adapter; keep typed config errors).
        _ = builder(settings, model, base_url)

        if effective == "ollama":
            config = _ollama_runtime_config(
                settings, model=model, base_url=base_url
            )
            if not config.base_url or not config.model:
                # builder() already validated; keep a local guard for the checker.
                raise MissingProviderCredentialsError(
                    "Missing OLLAMA_BASE_URL or OLLAMA_MODEL."
                )
            base = config.base_url.rstrip("/")
            try:
                inner = ChatOpenAI(
                    model=config.model,
                    api_key=SecretStr("ollama"),
                    base_url=f"{base}/v1",
                    timeout=config.timeout,
                )
            except Exception as exc:
                raise ProviderError(
                    "The tool-calling agent provider could not be reached."
                ) from exc
            model_name = config.model
        else:
            config = _openrouter_runtime_config(settings, model=model)
            if not config.api_key or not config.model:
                # builder() already validated; keep a local guard for the checker.
                raise MissingProviderCredentialsError(
                    "Missing OPENROUTER_API_KEY or OPENROUTER_MODEL."
                )
            try:
                inner = ChatOpenAI(
                    model=config.model,
                    api_key=SecretStr(config.api_key),
                    base_url=config.base_url,
                    timeout=config.timeout,
                )
            except Exception as exc:
                raise ProviderError(
                    "The tool-calling agent provider could not be reached."
                ) from exc
            model_name = config.model

        return _ObservingChatOpenAI(
            inner, recorder=recorder, model_name=model_name
        )

    return factory


class _ObservingChatOpenAI:
    """Wrap a LangChain chat model so each invoke updates ``RecordingChatModel``.

    Only ``bind_tools`` and ``invoke`` are forwarded: those are the methods
    ``LangGraphToolAgent`` uses. Other LangChain surfaces (``stream``, ``batch``)
    raise ``AttributeError`` rather than silently bypassing the recorder.
    """

    def __init__(
        self,
        inner: object,
        *,
        recorder: RecordingChatModel | None,
        model_name: str | None,
    ) -> None:
        self._inner = inner
        self._recorder = recorder
        self._model_name = model_name

    def bind_tools(
        self, tools: Sequence[object], *args: object, **kwargs: object
    ) -> "_ObservingChatOpenAI":
        bound = self._inner.bind_tools(tools, *args, **kwargs)  # type: ignore[attr-defined]
        return _ObservingChatOpenAI(
            bound, recorder=self._recorder, model_name=self._model_name
        )

    def invoke(self, messages: object, **kwargs: object) -> object:
        import time

        from application.contracts import RunMeta
        from domain.errors import ProviderError
        from domain.models import Usage

        started = time.perf_counter()
        result: object | None = None
        error_type: str | None = None
        try:
            result = self._inner.invoke(messages, **kwargs)  # type: ignore[attr-defined]
            return result
        except ProviderError:
            error_type = "ProviderError"
            raise
        except Exception as exc:
            error_type = type(exc).__name__
            raise ProviderError(
                "The tool-calling agent provider could not be reached."
            ) from exc
        finally:
            if self._recorder is not None:
                latency_ms = int((time.perf_counter() - started) * 1000)
                usage = None
                if result is not None:
                    usage_meta = getattr(result, "usage_metadata", None)
                    if isinstance(usage_meta, Mapping):
                        usage = Usage(
                            prompt_tokens=usage_meta.get("input_tokens"),  # type: ignore[arg-type]
                            completion_tokens=usage_meta.get("output_tokens"),  # type: ignore[arg-type]
                            total_tokens=usage_meta.get("total_tokens"),  # type: ignore[arg-type]
                        )
                self._recorder.record(
                    RunMeta(
                        model=self._model_name,
                        latency_ms=latency_ms,
                        usage=usage,
                        settings={},
                        error_type=error_type,
                    )
                )


def probe_ollama(settings: Settings, base_url: str) -> dict:
    """Reachability check, with the timeout taken from settings."""
    return _probe_ollama(base_url, settings.ollama.timeout)
