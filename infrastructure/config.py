"""Configuration loaded at the edge. Only the composition root calls load_settings()."""

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

from dotenv import load_dotenv
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

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
        sql_path (Path | None): SQLite file used by the SQL catalog adapter.
            ``None`` when ``DOCUMENT_CATALOG_SQL_PATH`` is blank; rejected when
            composition builds the catalog.
        workspace_id (str | None): Bound SQL workspace identity. Stored as the
            stripped env value when present (including malformed values);
            validated when composition builds the catalog.
    """

    sql_path: Path | None
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
class GoogleOAuthSettings:
    """User OAuth for the Next.js Drive connection (not the CLI service account).

    Client secret is never exposed on HTTP responses. Token JSON is stored at
    ``token_path`` and is not loaded into this dataclass.

    Args:
        client_id (str | None): Google OAuth client ID.
        client_secret (str | None): Google OAuth client secret.
        redirect_uri (str | None): Exact allow-listed callback URL.
        frontend_redirect (str | None): Knowledge Hub URL after the callback.
        token_path (Path): Server-side connection file (refresh token + metadata).
        state_path (Path): Single-use CSRF state file.
        state_ttl_seconds (int): How long an issued ``state`` remains valid.
    """

    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str | None = None
    frontend_redirect: str | None = None
    token_path: Path = field(
        default_factory=lambda: _PROJECT_ROOT / "data" / "google-oauth-connection.json"
    )
    state_path: Path = field(
        default_factory=lambda: _PROJECT_ROOT / "data" / "google-oauth-state.json"
    )
    state_ttl_seconds: int = 600

    def __repr__(self) -> str:
        return (
            "GoogleOAuthSettings("
            f"client_id={self.client_id!r}, client_secret='***', "
            f"redirect_uri={self.redirect_uri!r}, "
            f"frontend_redirect={self.frontend_redirect!r}, "
            f"token_path={self.token_path!r}, state_path={self.state_path!r}, "
            f"state_ttl_seconds={self.state_ttl_seconds})"
        )


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
    google_oauth: GoogleOAuthSettings = field(default_factory=GoogleOAuthSettings)


def load_settings() -> Settings:
    """Read the environment once. The composition root is the only caller."""
    load_dotenv(override=False)
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
        google_oauth=_load_google_oauth_settings(),
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


def _require_google_oauth_json_path(path: Path, env_name: str) -> Path:
    """Reject in-repo grant paths that would not match the OAuth gitignore."""
    resolved = path.expanduser().resolve()
    if not resolved.is_relative_to(_PROJECT_ROOT.resolve()):
        return path
    if not resolved.name.startswith("google-oauth-") or not resolved.name.endswith(
        ".json"
    ):
        raise ValueError(
            f"{env_name} must use a google-oauth-*.json filename so the grant stays gitignored"
        )
    return path


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


def _optional_env(name: str, default: str | None = None) -> str | None:
    """Return a stripped env value, or ``None`` when absent or blank.

    Args:
        name: Environment variable name.
        default: Fallback when the variable is unset. Blank values still
            resolve to ``None`` (they do not fall through to ``default``).
    """
    raw = os.getenv(name, default)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _load_document_catalog_settings() -> DocumentCatalogSettings:
    raw_sql = _optional_env(
        "DOCUMENT_CATALOG_SQL_PATH", "data/catalog/catalog.sqlite"
    )
    # Blank is stored as None — validated at catalog build so HTTP bootstrap
    # and OpenAPI export stay catalog-agnostic.
    return DocumentCatalogSettings(
        sql_path=_resolve_under_project_root(raw_sql) if raw_sql else None,
        workspace_id=_optional_env("DOCUMENT_CATALOG_WORKSPACE_ID"),
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
    raw_file = _optional_env("GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE")
    service_account_file = (
        _resolve_under_project_root(raw_file) if raw_file else None
    )
    # Charset checks run when the connector is built so HTTP/OpenAPI bootstrap
    # stays Drive-agnostic.
    folder_id = _optional_env("GOOGLE_DRIVE_FOLDER_ID")
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


def _require_absolute_http_url(name: str, raw: str) -> str:
    """Reject relative paths and non-http(s) schemes for OAuth redirects."""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute http(s) URL")
    return raw


def _load_google_oauth_settings() -> GoogleOAuthSettings:
    """Parse user-OAuth env without reading stored refresh tokens."""
    client_id = _optional_env("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = _optional_env("GOOGLE_OAUTH_CLIENT_SECRET")
    raw_redirect = _optional_env("GOOGLE_OAUTH_REDIRECT_URI")
    raw_frontend = _optional_env("GOOGLE_OAUTH_FRONTEND_REDIRECT")
    raw_token = _optional_env("GOOGLE_OAUTH_TOKEN_PATH")
    raw_state = _optional_env("GOOGLE_OAUTH_STATE_PATH")
    ttl = _env_int("GOOGLE_OAUTH_STATE_TTL_SECONDS", "600")
    if ttl < 30:
        raise ValueError("GOOGLE_OAUTH_STATE_TTL_SECONDS must be at least 30")
    redirect_uri = (
        _require_absolute_http_url("GOOGLE_OAUTH_REDIRECT_URI", raw_redirect)
        if raw_redirect
        else None
    )
    frontend_redirect = (
        _require_absolute_http_url("GOOGLE_OAUTH_FRONTEND_REDIRECT", raw_frontend)
        if raw_frontend
        else None
    )
    token_path = _require_google_oauth_json_path(
        (
            _resolve_under_project_root(raw_token)
            if raw_token
            else _PROJECT_ROOT / "data" / "google-oauth-connection.json"
        ),
        "GOOGLE_OAUTH_TOKEN_PATH",
    )
    state_path = _require_google_oauth_json_path(
        (
            _resolve_under_project_root(raw_state)
            if raw_state
            else _PROJECT_ROOT / "data" / "google-oauth-state.json"
        ),
        "GOOGLE_OAUTH_STATE_PATH",
    )
    return GoogleOAuthSettings(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        frontend_redirect=frontend_redirect,
        token_path=token_path,
        state_path=state_path,
        state_ttl_seconds=ttl,
    )
