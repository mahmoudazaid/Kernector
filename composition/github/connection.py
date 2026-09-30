"""GitHub connection: OAuth grant lifecycle, status, and connector-scoped purges."""

import importlib.util
import logging
from collections.abc import Callable
from dataclasses import replace
from typing import NoReturn

from application.errors import (
    ConfigurationError,
    GitHubNotConnectedError,
    GitHubReauthorizationRequiredError,
)
from composition import container as _container
from composition.errors import DocumentOperationError
from composition.github.models import (
    GitHubLastSync,
    GitHubStatus,
)
from domain.errors import (
    ConnectorAuthError,
    VectorStoreError,
)
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceDocument,
    SourceLocator,
    SourceType,
)
from domain.ports import (
    DocumentCatalog,
    VectorStore,
)
from infrastructure.catalog.errors import CatalogError
from infrastructure.config import Settings

logger = logging.getLogger(__name__)


class AuthRetryingGitHubIssueReader:
    """Live issue reader that refreshes the GitHub grant once on auth failure."""

    def __init__(
        self,
        *,
        settings: Settings,
        access_token: str,
        tokens_store,
        connection,
        oauth_gateway=None,
        client_factory=None,
    ) -> None:
        self._settings = settings
        self._access_token = access_token
        self._tokens_store = tokens_store
        self._connection = connection
        self._oauth_gateway = oauth_gateway
        self._client_factory = client_factory

    def fetch(self, locator: SourceLocator) -> SourceDocument:
        from infrastructure.connectors.github.issue_source_reader import (
            GitHubIssueSourceReader,
        )

        try:
            client = github_picker_client(
                self._settings,
                access_token=self._access_token,
                client_factory=self._client_factory,
            )
            return GitHubIssueSourceReader(client).fetch(locator)
        except ConnectorAuthError as error:
            refreshed = _refresh_github_grant_access_token(
                self._settings,
                tokens_store=self._tokens_store,
                connection=self._connection,
                oauth_gateway=self._oauth_gateway,
                cause=error,
            )
            try:
                client = github_picker_client(
                    self._settings,
                    access_token=refreshed,
                    client_factory=self._client_factory,
                )
                return GitHubIssueSourceReader(client).fetch(locator)
            except ConnectorAuthError as retry_error:
                mark_github_reauth(self._tokens_store, retry_error)


def _refresh_github_grant_access_token(
    settings: Settings,
    *,
    tokens_store,
    connection,
    oauth_gateway=None,
    cause: BaseException,
) -> str:
    """Refresh and persist a GitHub user grant; mark reauth when refresh is impossible."""
    from infrastructure.connectors.github.oauth import (
        GitHubOAuthError,
        HttpGitHubOAuthGateway,
    )

    if not connection.refresh_token:
        mark_github_reauth(tokens_store, cause)
    gateway = (
        oauth_gateway
        if oauth_gateway is not None
        else HttpGitHubOAuthGateway(settings.github_oauth)
    )
    try:
        grant = gateway.refresh(connection.refresh_token)
    except GitHubOAuthError as refresh_error:
        mark_github_reauth(tokens_store, refresh_error)
    access_token = grant.access_token
    refresh_token = grant.refresh_token or connection.refresh_token
    tokens_store.mutate(
        lambda current: None
        if current is None
        else replace(
            current,
            access_token=access_token,
            refresh_token=refresh_token,
            reauthorization_required=False,
        )
    )
    return access_token


GITHUB_CLIENT_MISSING_MESSAGE = (
    "GitHub client is not installed; run uv sync --extra github."
)


def _github_oauth_ready(settings: Settings) -> bool:
    oauth = settings.github_oauth
    return bool(oauth.client_id and oauth.client_secret and oauth.redirect_uri)


def _github_connection_store(settings: Settings):
    from infrastructure.connectors.github.oauth import GitHubOAuthConnectionStore

    return GitHubOAuthConnectionStore(settings.github_oauth.token_path)


def _github_state_store(settings: Settings):
    from infrastructure.connectors.github.oauth import GitHubOAuthStateStore

    return GitHubOAuthStateStore(
        settings.github_oauth.state_path,
        ttl_seconds=settings.github_oauth.state_ttl_seconds,
    )


def _github_hub_redirect(settings: Settings, *, result: str) -> str:
    base = settings.github_oauth.frontend_redirect
    if base is None:
        origin = (
            settings.http.cors_origins[0]
            if settings.http.cors_origins
            else "http://localhost:3000"
        )
        base = f"{origin.rstrip('/')}/documents"
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}github={result}"


def github_status(
    settings: Settings,
    *,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
) -> GitHubStatus:
    """Report PAT flags plus user OAuth connection metadata."""
    github = settings.github
    connection = _github_connection_store(settings).load()
    configured = bool(github.token and github.owner and github.repo)
    available = importlib.util.find_spec("httpx") is not None
    last_sync = None
    if (
        connection is not None
        and connection.last_synced_at is not None
        and connection.last_sync_new is not None
        and connection.last_sync_updated is not None
        and connection.last_sync_unchanged is not None
        and connection.last_sync_removed is not None
        and connection.last_sync_failed is not None
    ):
        last_sync = GitHubLastSync(
            synced_at=connection.last_synced_at,
            new_count=connection.last_sync_new,
            updated_count=connection.last_sync_updated,
            unchanged_count=connection.last_sync_unchanged,
            removed_count=connection.last_sync_removed,
            failed_count=connection.last_sync_failed,
        )
    reauthorization_required = (
        False if connection is None else connection.reauthorization_required
    )
    # Hub selection on the grant wins; env is a fallback for pre-seeded operators.
    owner = coalesce_text(
        None if connection is None else connection.owner,
        settings.github.owner,
    )
    repo = coalesce_text(
        None if connection is None else connection.repo,
        settings.github.repo,
    )
    project_owner = coalesce_text(
        None if connection is None else connection.project_owner,
        settings.github.project_owner,
    )
    project_number = (
        None if connection is None else connection.project_number
    )
    if project_number is None:
        project_number = settings.github.project_number
    has_scope = bool(
        (owner and repo) or (project_owner and project_number is not None)
    )
    setup_required = bool(
        connection is not None
        and not reauthorization_required
        and not has_scope
    )
    if connection is None:
        connection_state = "disconnected"
    elif reauthorization_required:
        connection_state = "reauthorization_required"
    elif setup_required:
        connection_state = "setup_required"
    else:
        connection_state = "ready"
    return GitHubStatus(
        configured=configured,
        available=available,
        connected=connection is not None,
        oauth_ready=_github_oauth_ready(settings),
        account_login=None if connection is None else connection.account_login,
        document_count=_github_document_count(
            settings,
            connection=connection,
            catalog=catalog,
            catalog_factory=catalog_factory,
        ),
        owner=owner,
        repo=repo,
        project_owner=project_owner,
        project_number=project_number,
        last_sync=last_sync,
        reauthorization_required=reauthorization_required,
        connection_state=connection_state,
        sync_scope=_github_sync_scope(
            owner=owner,
            repo=repo,
            project_owner=project_owner,
            project_number=project_number,
        ),
        setup_required=setup_required,
    )


def coalesce_text(preferred: str | None, fallback: str | None) -> str | None:
    if isinstance(preferred, str) and preferred.strip():
        return preferred.strip()
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return None


def _github_document_count(
    settings: Settings,
    *,
    connection,
    catalog: DocumentCatalog | None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
) -> int:
    if connection is None and not (
        settings.github.token and settings.github.owner and settings.github.repo
    ):
        return 0
    try:
        working = _container.resolve_catalog(
            settings, catalog=catalog, catalog_factory=catalog_factory
        )
        return working.count(
            source_type=SourceType.GITHUB,
            status=CatalogStatus.READY,
        )
    except (
        CatalogError,
        ConfigurationError,
        DocumentOperationError,
        OSError,
        ValueError,
    ):
        logger.warning("GitHub document count unavailable", exc_info=True)
        return 0


def _github_sync_scope(
    *,
    owner: str | None,
    repo: str | None,
    project_owner: str | None = None,
    project_number: int | None = None,
) -> str | None:
    parts: list[str] = []
    if owner and repo:
        parts.append(f"{owner}/{repo}")
    if project_owner and project_number is not None:
        parts.append(f"{project_owner}#{project_number}")
    if not parts:
        return None
    return " · ".join(parts)


def require_github_grant(settings: Settings, *, connection_store=None):
    tokens_store = (
        connection_store
        if connection_store is not None
        else _github_connection_store(settings)
    )
    connection = tokens_store.load()
    if connection is None:
        raise GitHubNotConnectedError("GitHub is not connected")
    if connection.reauthorization_required:
        raise GitHubReauthorizationRequiredError("GitHub authorization was revoked")
    return tokens_store, connection


def mark_github_reauth(tokens_store, error: BaseException) -> NoReturn:
    tokens_store.mutate(
        lambda current: None
        if current is None
        else replace(current, reauthorization_required=True)
    )
    raise GitHubReauthorizationRequiredError(
        "GitHub authorization was revoked"
    ) from error


def start_github_oauth(
    settings: Settings,
    *,
    state_store=None,
) -> str:
    """Issue CSRF state and return GitHub's authorization URL."""
    if not _github_oauth_ready(settings):
        return _github_hub_redirect(settings, result="unconfigured")
    from infrastructure.connectors.github.oauth import authorization_url

    store = state_store if state_store is not None else _github_state_store(settings)
    state = store.issue()
    return authorization_url(settings.github_oauth, state=state)


def complete_github_oauth(
    settings: Settings,
    *,
    state: str | None,
    code: str | None,
    error: str | None,
    state_store=None,
    connection_store=None,
    gateway=None,
) -> str:
    """Validate callback query params, persist the GitHub grant, return Hub URL."""
    if error == "access_denied":
        return _github_hub_redirect(settings, result="denied")
    store = state_store if state_store is not None else _github_state_store(settings)
    if not store.consume(state):
        return _github_hub_redirect(settings, result="invalid_state")
    if error or not code:
        return _github_hub_redirect(settings, result="error")
    if not _github_oauth_ready(settings):
        return _github_hub_redirect(settings, result="error")
    from infrastructure.connectors.github.oauth import (
        GitHubOAuthConnection,
        GitHubOAuthError,
        HttpGitHubOAuthGateway,
    )

    oauth_gateway = gateway if gateway is not None else HttpGitHubOAuthGateway(
        settings.github_oauth
    )
    tokens_store = (
        connection_store
        if connection_store is not None
        else _github_connection_store(settings)
    )
    try:
        grant = oauth_gateway.exchange_code(code)
        login = oauth_gateway.fetch_account_login(grant.access_token)

        def _next(_existing):
            # Pre-seed from env when present so existing operators keep working;
            # Hub selection can replace these after Connect.
            return GitHubOAuthConnection(
                access_token=grant.access_token,
                refresh_token=grant.refresh_token,
                account_login=login,
                owner=settings.github.owner,
                repo=settings.github.repo,
                project_owner=settings.github.project_owner,
                project_number=settings.github.project_number,
                last_synced_at=None,
                last_sync_new=None,
                last_sync_updated=None,
                last_sync_unchanged=None,
                last_sync_removed=None,
                last_sync_failed=None,
                reauthorization_required=False,
            )

        tokens_store.mutate(_next)
    except GitHubOAuthError:
        return _github_hub_redirect(settings, result="error")
    return _github_hub_redirect(settings, result="connected")


def disconnect_github_oauth(
    settings: Settings,
    *,
    connection_store=None,
    gateway=None,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
) -> None:
    """Revoke the stored access token, delete the local grant, and purge docs.

    Synced GitHub catalog rows for this connection's ``connector_id`` (repository
    files and ProjectV2 issues) are removed from the catalog and vector store.
    """
    tokens_store = (
        connection_store
        if connection_store is not None
        else _github_connection_store(settings)
    )
    connection = tokens_store.load()
    if connection is None:
        raise GitHubNotConnectedError("GitHub is not connected")
    from infrastructure.connectors.github.oauth import HttpGitHubOAuthGateway

    oauth_gateway = gateway if gateway is not None else HttpGitHubOAuthGateway(
        settings.github_oauth
    )
    connector_id = connection.connector_id
    oauth_gateway.revoke(connection.access_token)
    tokens_store.clear()
    purge_github_connector_docs(
        settings,
        connector_id=connector_id,
        catalog=catalog,
        catalog_factory=catalog_factory,
        vector_store=vector_store,
        vector_store_factory=vector_store_factory,
    )


_GITHUB_ISSUE_SOURCE_ID_PREFIX = "issue:"


def _github_row_in_connector_scope(
    row: CatalogDocument, connector_ids: frozenset[str]
) -> bool:
    if not connector_ids:
        return True
    if row.connector_id is None:
        return True
    return row.connector_id in connector_ids


def purge_github_connector_docs(
    settings: Settings,
    *,
    connector_id: str | None,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
    source_id_prefixes: tuple[str, ...] | None = None,
) -> None:
    """Delete GitHub catalog+vector rows for ``connector_id``.

    When ``source_id_prefixes`` is set, only matching source ids are removed.
    Otherwise every GitHub row in connector scope is removed (disconnect).
    """
    working = _container.resolve_catalog(
        settings, catalog=catalog, catalog_factory=catalog_factory
    )
    connector_ids = (
        frozenset({connector_id.strip()})
        if isinstance(connector_id, str) and connector_id.strip()
        else frozenset()
    )
    prefixes = source_id_prefixes
    targets = [
        row
        for row in working.all()
        if row.reference.source_type == SourceType.GITHUB
        and (
            prefixes is None
            or any(
                row.reference.source_id.startswith(prefix) for prefix in prefixes
            )
        )
        and _github_row_in_connector_scope(row, connector_ids)
    ]
    if not targets:
        return

    get_store = _container.lazy_vector_store(
        settings,
        vector_store=vector_store,
        vector_store_factory=vector_store_factory,
    )
    store = get_store()
    try:
        for row in targets:
            store.delete_source(row.reference)
            working.delete(row.reference)
    except CatalogError as error:
        raise DocumentOperationError(str(error)) from error
    except VectorStoreError as error:
        raise DocumentOperationError(str(error)) from error


def purge_github_dropped_selection_docs(
    settings: Settings,
    *,
    previous_owner: str | None,
    previous_repo: str | None,
    previous_project_owner: str | None,
    previous_project_number: int | None,
    new_owner: str | None,
    new_repo: str | None,
    new_project_owner: str | None,
    new_project_number: int | None,
    connector_id: str | None,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
) -> None:
    """Delete catalog+vector rows for repo/project scopes dropped by selection."""
    prefixes: list[str] = []
    if previous_owner and previous_repo:
        old_repo = (previous_owner, previous_repo)
        new_repo_pair = (new_owner, new_repo) if new_owner and new_repo else None
        if old_repo != new_repo_pair:
            prefixes.append(f"{previous_owner}/{previous_repo}:")
    if previous_project_owner and previous_project_number is not None:
        old_project = (previous_project_owner, previous_project_number)
        new_project = (
            (new_project_owner, new_project_number)
            if new_project_owner and new_project_number is not None
            else None
        )
        if old_project != new_project:
            prefixes.append(_GITHUB_ISSUE_SOURCE_ID_PREFIX)
    if not prefixes:
        return

    purge_github_connector_docs(
        settings,
        connector_id=connector_id,
        catalog=catalog,
        catalog_factory=catalog_factory,
        vector_store=vector_store,
        vector_store_factory=vector_store_factory,
        source_id_prefixes=tuple(prefixes),
    )


def github_picker_client(
    settings: Settings,
    *,
    access_token: str,
    client_factory=None,
):
    if client_factory is not None:
        return client_factory(access_token)
    try:
        from infrastructure.connectors.github.client import HttpGitHubClient
    except ImportError as error:
        raise ConfigurationError(GITHUB_CLIENT_MISSING_MESSAGE) from error
    return HttpGitHubClient(access_token, page_size=settings.github.page_size)
