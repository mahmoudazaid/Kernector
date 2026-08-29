"""Composition root: the only place that constructs infrastructure."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from application.ask_service import AskService
from application.contracts import IngestRequest, IngestResponse
from application.errors import ApplicationValidationError, ConfigurationError
from application.ingest_knowledge import IngestFailure, IngestKnowledge
from application.manage_documents import (
    DocumentManagementError,
    ManageUploadedDocuments,
    PartialCreateFailure,
    PartialDeleteFailure,
    PartialReplaceFailure,
    UnknownDocumentError,
)
from application.retrieve_knowledge import RetrieveKnowledge
from composition.errors import (
    DocumentOperationError,
    DocumentUploadError,
    KnowledgeLoadError,
    PartialDocumentOperationError,
)
from domain.errors import DomainValidationError
from domain.knowledge import CatalogDocument, SourceDocument, SourceReference, UploadPayload
from domain.ports import ChatModel, DocumentCatalog, EmbeddingModel, PromptRepository, VectorStore
from infrastructure.catalog.json_catalog import CatalogError, JsonDocumentCatalog
from infrastructure.config import Settings, load_settings
from infrastructure.documents.uploaded_files import (
    SUPPORTED_SUFFIXES,
    DocumentExtractionError,
    UploadedFileExtractor,
    extract_document,
)
from infrastructure.embeddings.openrouter import (
    EmbeddingConfigError,
    OpenRouterEmbeddings,
)
from infrastructure.knowledge.corpus import CorpusLoadError, load_knowledge_corpus
from infrastructure.llm.ollama import OllamaChat
from infrastructure.llm.ollama import probe_ollama as _probe_ollama
from infrastructure.llm.openrouter import OpenRouterChat
from infrastructure.prompts.markdown_repository import MarkdownPromptRepository
from infrastructure.vectorstore.chroma import ChromaStoreError, ChromaVectorStore

SUPPORTED_UPLOAD_SUFFIXES: frozenset[str] = SUPPORTED_SUFFIXES

logger = logging.getLogger(__name__)



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

    Raises:
        ConfigurationError: The embedding credentials are missing or unusable.
    """
    try:
        embedding_model = build_embedding_model(settings)
    except EmbeddingConfigError as exc:
        raise ConfigurationError(str(exc)) from exc
    if vector_store is None:
        vector_store = build_vector_store(settings)
    return RetrieveKnowledge(embedding_model, vector_store)


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
    """Build a fresh JSON catalog adapter for the configured path."""
    return JsonDocumentCatalog(settings.document_catalog.path)


def build_document_extractor() -> UploadedFileExtractor:
    """Build the upload-payload extractor adapter."""
    return UploadedFileExtractor()


def build_manage_uploaded_documents(settings: Settings) -> ManageUploadedDocuments:
    """Wire create/replace/delete/list for uploaded documents.

    The store and the ingest pipeline are passed as factories the use case calls
    only when it needs them. Listing then costs one JSON read — no Chroma client
    and no embedding credentials — which matters because the Streamlit page
    lists on every rerun, and because `list` and `delete` never embed anything.
    Each operation opens at most one store, and both paths open it through the
    same factory, so ingest and delete cannot drift onto different collections.
    """
    def _vector_store() -> VectorStore:
        return build_vector_store(settings)

    def _ingest() -> IngestKnowledge:
        return build_ingest_knowledge(settings, vector_store=_vector_store())

    return ManageUploadedDocuments(
        catalog=build_document_catalog(settings),
        extractor=build_document_extractor(),
        ingest_factory=_ingest,
        vector_store_factory=_vector_store,
    )


def list_uploaded_documents(settings: Settings) -> tuple[CatalogDocument, ...]:
    """Return every uploaded-document catalog row."""
    try:
        return tuple(build_manage_uploaded_documents(settings).list())
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error


def create_uploaded_document(
    settings: Settings, payload: UploadPayload
) -> CatalogDocument:
    """Create a new uploaded document with a system-managed source ID.

    Raises:
        PartialDocumentOperationError: The upload failed and its catalog status
            could not be written, so a stale row may be visible.
        DocumentUploadError: The file could not be extracted or ingested.
        DocumentOperationError: The catalog could not be read or written.
    """
    try:
        return build_manage_uploaded_documents(settings).create(payload)
    except DocumentExtractionError as error:
        raise DocumentUploadError(str(error)) from error
    except DomainValidationError as error:
        raise DocumentUploadError(str(error)) from error
    except PartialCreateFailure as error:
        _log_partial_create(error)
        raise PartialDocumentOperationError(str(error)) from error
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
) -> CatalogDocument:
    """Replace an existing uploaded document under the same source ID.

    Raises:
        PartialDocumentOperationError: Chunks or the catalog row were left
            mid-replace, so a retry is genuinely required.
        DocumentOperationError: The replace stopped without mutating anything.
        DocumentUploadError: The replacement file could not be extracted.
    """
    try:
        return build_manage_uploaded_documents(settings).replace(reference, payload)
    except UnknownDocumentError as error:
        raise DocumentOperationError(str(error)) from error
    except DocumentExtractionError as error:
        raise DocumentUploadError(str(error)) from error
    except DomainValidationError as error:
        raise DocumentUploadError(str(error)) from error
    except PartialReplaceFailure as error:
        raise PartialDocumentOperationError(str(error)) from error
    except IngestFailure as error:
        # A failure before the first `delete_source` left the previous version
        # stored and its catalog row restored: nothing for the user to retry.
        if error.vector_mutation_started:
            raise PartialDocumentOperationError(str(error)) from error
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
    settings: Settings, reference: SourceReference
) -> None:
    """Delete vector chunks then the catalog row for ``reference``.

    Raises:
        PartialDocumentOperationError: The chunks are gone but the catalog row
            remains, so a retry is genuinely required.
        DocumentOperationError: The delete stopped before removing anything.
    """
    try:
        build_manage_uploaded_documents(settings).delete(reference)
    except PartialDeleteFailure as error:
        raise PartialDocumentOperationError(str(error)) from error
    except DocumentManagementError as error:
        raise DocumentOperationError(str(error)) from error
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error


def build_prompt_repository(settings: Settings) -> PromptRepository:
    return MarkdownPromptRepository(
        settings.prompts.pack_paths,
        default_key=settings.prompts.default_key,
    )


def build_ask_service(chat_model: ChatModel) -> AskService:
    return AskService(chat_model)


def probe_ollama(settings: Settings, base_url: str) -> dict:
    """Reachability check, with the timeout taken from settings."""
    return _probe_ollama(base_url, settings.ollama.timeout)
