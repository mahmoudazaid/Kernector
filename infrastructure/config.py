"""Configuration loaded at the edge. Only the composition root calls load_settings()."""

import os
import re
from dataclasses import dataclass, field

from dotenv import load_dotenv
from pathlib import Path

from infrastructure.catalog.workspace import parse_workspace_id

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
# fullmatch is load-bearing: .match()/.search() would accept injection prefixes.
_GOOGLE_DRIVE_FOLDER_ID = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True, slots=True)
class OpenRouterSettings:
    api_key: str | None
    base_url: str | None
    model: str | None
    models: tuple[str, ...]
    embedding_model: str
    rewrite_model: str | None
    timeout: float


@dataclass(frozen=True, slots=True)
class OllamaSettings:
    base_url: str | None
    model: str | None
    timeout: float


@dataclass(frozen=True, slots=True)
class ChunkingSettings:
    chunk_size: int
    chunk_overlap: int

@dataclass(frozen=True, slots=True)
class ChromaSettings:
    persist_path: Path
    collection: str


@dataclass(frozen=True, slots=True)
class KnowledgeSettings:
    corpus_path: Path


@dataclass(frozen=True, slots=True)
class DocumentCatalogSettings:
    """Uploaded-document catalog adapter configuration.

    Args:
        path (Path): JSON catalog file used by the JSON adapter and as the
            importer source.
        backend (str): Selected adapter, ``json`` or ``sql``.
        sql_path (Path): SQLite file used by the SQL adapter.
        workspace_id (str | None): Bound SQL workspace. Required when
            ``backend`` is ``sql``; optional and validated when present under
            JSON.
    """

    path: Path
    backend: str
    sql_path: Path
    workspace_id: str | None


@dataclass(frozen=True, slots=True)
class PromptSettings:
    pack_paths: tuple[Path, ...]
    default_key: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalSettings:
    """How much evidence to fetch, and how close it must be to count.

    `relevance_threshold` is always a raw cosine similarity floor in
    [-1.0, 1.0], matching `VectorStore.search` scores. The default of 0.0
    discards only actively dissimilar vector chunks. Raising it is what makes
    the insufficient-knowledge path fire on merely-unrelated results; the right
    number depends on the embedding model and corpus — measure the score
    spread over known on-topic and off-topic queries before setting it.

    When `hybrid_enabled` is true, that same value is applied as the vector-
    channel eligibility floor *before* normalization and fusion. Hybrid hit
    scores returned to ask/tool paths are fused ranking scores in [0, 1], not
    absolute relevance probabilities — do not reinterpret
    `relevance_threshold` against those fused values. Lexical eligibility is
    controlled by BM25 token overlap, not this cosine floor.

    `hybrid_alpha` weights BM25 (1 = BM25 only, 0 = vector only).
    """

    limit: int
    relevance_threshold: float
    hybrid_enabled: bool = False
    hybrid_alpha: float = 0.5


@dataclass(frozen=True, slots=True)
class DomainToolSettings:
    """Optional executable domain tool packs enabled at composition time."""

    enabled_packs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HttpAdapterSettings:
    """HTTP presentation adapter flags (CORS). Loaded with the rest of Settings."""

    dev_cors: bool
    cors_origins: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoogleDriveSettings:
    """Optional Google Drive connector configuration.

    Credential JSON is never loaded into Settings; only the path is stored.
    Presence of the path and folder ID is validated when the connector is built.

    Args:
        service_account_file (Path | None): Path to a service-account JSON key.
        folder_id (str | None): Drive folder whose direct children are synced.
        page_size (int): Drive list page size, from 1 to 1000 inclusive.
    """

    service_account_file: Path | None = None
    folder_id: str | None = None
    page_size: int = 100


@dataclass(frozen=True, slots=True)
class Settings:
    provider: str
    max_input_length: int
    max_upload_bytes: int
    openrouter: OpenRouterSettings
    ollama: OllamaSettings
    chunking: ChunkingSettings
    chroma: ChromaSettings
    knowledge: KnowledgeSettings
    document_catalog: DocumentCatalogSettings
    prompts: PromptSettings
    retrieval: RetrievalSettings
    domain_tools: DomainToolSettings
    http: HttpAdapterSettings
    google_drive: GoogleDriveSettings = field(default_factory=GoogleDriveSettings)


def load_settings() -> Settings:
    """Read the environment once. The composition root is the only caller."""
    load_dotenv(override=True)
    max_input_length = _env_int("MAX_INPUT_LENGTH", "10000")
    if max_input_length <= 0:
        raise ValueError(f"MAX_INPUT_LENGTH must be > 0, got {max_input_length}")
    max_upload_bytes = _env_int("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))
    if max_upload_bytes <= 0:
        raise ValueError(f"MAX_UPLOAD_BYTES must be > 0, got {max_upload_bytes}")
    return Settings(
        provider=os.getenv("LLM_PROVIDER", "openrouter").lower(),
        max_input_length=max_input_length,
        max_upload_bytes=max_upload_bytes,
        openrouter=OpenRouterSettings(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=os.getenv("OPENROUTER_BASE_URL"),
            model=os.getenv("OPENROUTER_MODEL"),
            models=_csv(os.getenv("OPENROUTER_MODELS", "")),
            embedding_model=os.getenv(
                "OPENROUTER_EMBEDDING_MODEL", "qwen/qwen3-embedding-8b"
            ),
            rewrite_model=os.getenv("OPENROUTER_REWRITE_MODEL")
            or os.getenv("OPENROUTER_MODEL"),
            timeout=float(os.getenv("OPENROUTER_TIMEOUT", "120")),
        ),
        ollama=OllamaSettings(
            base_url=os.getenv("OLLAMA_BASE_URL"),
            model=os.getenv("OLLAMA_MODEL"),
            timeout=float(os.getenv("OLLAMA_TIMEOUT", "120")),
        ),
        chunking=_load_chunking_settings(),
        chroma=_load_chroma_settings(),
        knowledge=_load_knowledge_settings(),
        document_catalog=_load_document_catalog_settings(),
        prompts=_load_prompt_settings(),
        retrieval=_load_retrieval_settings(),
        domain_tools=_load_domain_tool_settings(),
        http=_load_http_adapter_settings(),
        google_drive=_load_google_drive_settings(),
    )


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _env_int(name: str, default: str) -> int:
    raw = os.getenv(name, default)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _load_chunking_settings() -> ChunkingSettings:
    chunk_size = _env_int("CHUNK_SIZE", "500")
    chunk_overlap = _env_int("CHUNK_OVERLAP", "50")
    if chunk_size <= 0:
        raise ValueError(f"CHUNK_SIZE must be > 0, got {chunk_size}")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError(
            "CHUNK_OVERLAP must satisfy 0 <= overlap < CHUNK_SIZE, "
            f"got overlap={chunk_overlap}, size={chunk_size}"
        )
    return ChunkingSettings(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

def _resolve_under_project_root(raw: str) -> Path:
    """Expand `~`, keep absolute paths, resolve relative ones against the repo root.

    Deliberately not resolved against the CWD, so paths land in the same place
    whether the app is launched from the repo root or elsewhere.
    """
    path = Path(raw).expanduser()
    return path if path.is_absolute() else _PROJECT_ROOT / path


def _load_chroma_settings() -> ChromaSettings:
    collection = os.getenv("CHROMA_COLLECTION", "kernector_knowledge")
    if not collection.strip():
        raise ValueError(f"CHROMA_COLLECTION must be non-empty, got {collection!r}")
    persist_path = os.getenv("CHROMA_PERSIST_PATH", "data/chroma")
    if not persist_path.strip():
        raise ValueError(
            f"CHROMA_PERSIST_PATH must be non-empty, got {persist_path!r}"
        )
    return ChromaSettings(
        persist_path=_resolve_under_project_root(persist_path),
        collection=collection,
    )


def _load_knowledge_settings() -> KnowledgeSettings:
    corpus_path = os.getenv(
        "KNOWLEDGE_CORPUS_PATH", "data/knowledge/documents.json"
    )
    if not corpus_path.strip():
        raise ValueError(
            f"KNOWLEDGE_CORPUS_PATH must be non-empty, got {corpus_path!r}"
        )
    return KnowledgeSettings(
        corpus_path=_resolve_under_project_root(corpus_path),
    )


def _load_document_catalog_settings() -> DocumentCatalogSettings:
    catalog_path = os.getenv(
        "DOCUMENT_CATALOG_PATH", "data/catalog/uploads.json"
    )
    if not catalog_path.strip():
        raise ValueError(
            f"DOCUMENT_CATALOG_PATH must be non-empty, got {catalog_path!r}"
        )
    backend = os.getenv("DOCUMENT_CATALOG_BACKEND", "json").strip().lower()
    if backend not in {"json", "sql"}:
        raise ValueError(
            f"DOCUMENT_CATALOG_BACKEND must be 'json' or 'sql', got {backend!r}"
        )
    sql_path = os.getenv(
        "DOCUMENT_CATALOG_SQL_PATH", "data/catalog/catalog.sqlite"
    )
    if not sql_path.strip():
        raise ValueError(
            f"DOCUMENT_CATALOG_SQL_PATH must be non-empty, got {sql_path!r}"
        )
    try:
        workspace_id = parse_workspace_id(
            os.getenv("DOCUMENT_CATALOG_WORKSPACE_ID")
        )
    except ValueError as error:
        raise ValueError(
            f"DOCUMENT_CATALOG_WORKSPACE_ID {error}"
        ) from error
    if backend == "sql" and workspace_id is None:
        raise ValueError(
            "DOCUMENT_CATALOG_WORKSPACE_ID is required when "
            "DOCUMENT_CATALOG_BACKEND=sql"
        )
    return DocumentCatalogSettings(
        path=_resolve_under_project_root(catalog_path),
        backend=backend,
        sql_path=_resolve_under_project_root(sql_path),
        workspace_id=workspace_id,
    )


def _env_bool(name: str, default: str) -> bool:
    raw = os.getenv(name, default)
    if raw is None:
        raise ValueError(f"{name} must be a boolean, got {raw!r}")
    normalized = str(raw).strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be a boolean, got {raw!r}")


def _load_retrieval_settings() -> RetrievalSettings:
    limit = _env_int("RETRIEVAL_LIMIT", "5")
    if limit <= 0:
        raise ValueError(f"RETRIEVAL_LIMIT must be > 0, got {limit}")
    raw_threshold = os.getenv("RELEVANCE_THRESHOLD", "0.0")
    try:
        threshold = float(raw_threshold)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"RELEVANCE_THRESHOLD must be a number, got {raw_threshold!r}"
        ) from exc
    if not -1.0 <= threshold <= 1.0:
        raise ValueError(
            f"RELEVANCE_THRESHOLD must be within [-1.0, 1.0], got {threshold}"
        )
    hybrid_enabled = _env_bool("HYBRID_SEARCH_ENABLED", "false")
    raw_alpha = os.getenv("HYBRID_ALPHA", "0.5")
    try:
        hybrid_alpha = float(raw_alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"HYBRID_ALPHA must be a number, got {raw_alpha!r}"
        ) from exc
    if not 0.0 <= hybrid_alpha <= 1.0:
        raise ValueError(
            f"HYBRID_ALPHA must be within [0.0, 1.0], got {hybrid_alpha}"
        )
    return RetrievalSettings(
        limit=limit,
        relevance_threshold=threshold,
        hybrid_enabled=hybrid_enabled,
        hybrid_alpha=hybrid_alpha,
    )


def _load_prompt_settings() -> PromptSettings:
    raw = os.getenv("PROMPT_PACKS", "core")
    names = _csv(raw)
    default_key_raw = os.getenv("PROMPT_DEFAULT_KEY")
    default_key: str | None
    if default_key_raw is None:
        default_key = None
    elif not default_key_raw.strip():
        raise ValueError(
            f"PROMPT_DEFAULT_KEY must be non-empty, got {default_key_raw!r}"
        )
    else:
        default_key = default_key_raw.strip()
    return PromptSettings(
        pack_paths=tuple(
            _PROJECT_ROOT / "prompts" / "packs" / name for name in names
        ),
        default_key=default_key,
    )


def _load_domain_tool_settings() -> DomainToolSettings:
    raw = os.getenv("DOMAIN_TOOL_PACKS", "")
    names = _csv(raw)
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name in seen:
            raise ValueError(
                f"DOMAIN_TOOL_PACKS contains duplicate pack id: {name!r}"
            )
        seen.add(name)
        ordered.append(name)
    return DomainToolSettings(enabled_packs=tuple(ordered))


def _env_truthy(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _load_http_adapter_settings() -> HttpAdapterSettings:
    """Parse HTTP adapter CORS flags (after ``load_dotenv``).

    ``HTTP_CORS_ORIGINS`` must not include ``*`` — that would be a permissive
    production default. Rejection lives here (not only in the HTTP adapter) so
    the CLI and any future non-HTTP adapter also refuse to start with that
    misconfiguration:
    ``*`` in shared Settings is never a safe process-wide default. When
    ``HTTP_DEV_CORS`` is off, origins are ignored at the adapter but the
    ``*`` check still runs at load time.
    """
    origins = _csv(os.getenv("HTTP_CORS_ORIGINS", "http://localhost:3000"))
    if "*" in origins:
        raise ValueError(
            "HTTP_CORS_ORIGINS must not include '*'; list explicit origins"
        )
    return HttpAdapterSettings(
        dev_cors=_env_truthy("HTTP_DEV_CORS"),
        cors_origins=origins,
    )


def _load_google_drive_settings() -> GoogleDriveSettings:
    """Parse optional Drive connector env vars without reading credential JSON."""
    raw_file = os.getenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE")
    service_account_file: Path | None
    if raw_file is None or not raw_file.strip():
        service_account_file = None
    else:
        service_account_file = _resolve_under_project_root(raw_file.strip())
    raw_folder = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
    folder_id: str | None
    if raw_folder is None or not raw_folder.strip():
        folder_id = None
    else:
        folder_id = raw_folder.strip()
        if not _GOOGLE_DRIVE_FOLDER_ID.fullmatch(folder_id):
            raise ValueError(
                "GOOGLE_DRIVE_FOLDER_ID must be a Drive folder ID "
                "(letters, digits, `-`, `_`); it looks like you pasted a URL or path"
            )
    page_size = _env_int("GOOGLE_DRIVE_PAGE_SIZE", "100")
    if not 1 <= page_size <= 1000:
        raise ValueError(
            f"GOOGLE_DRIVE_PAGE_SIZE must satisfy 1 <= page_size <= 1000, "
            f"got {page_size}"
        )
    return GoogleDriveSettings(
        service_account_file=service_account_file,
        folder_id=folder_id,
        page_size=page_size,
    )
