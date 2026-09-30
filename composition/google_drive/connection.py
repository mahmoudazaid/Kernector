"""Google Drive connection: OAuth grant lifecycle, status, and purges."""

import importlib.util
import logging
from collections.abc import Callable
from dataclasses import replace
from typing import NoReturn

from application.errors import (
    ConfigurationError,
    GoogleDriveNotConnectedError,
    GoogleDriveReauthorizationRequiredError,
)
from composition import container as _container
from composition.errors import DocumentOperationError
from composition.google_drive.models import (
    GoogleDriveLastSync,
    GoogleDriveStatus,
)
from domain.errors import VectorStoreError
from domain.knowledge import (
    CatalogStatus,
    SourceType,
)
from domain.ports import (
    DocumentCatalog,
    VectorStore,
)
from infrastructure.catalog.errors import CatalogError
from infrastructure.config import Settings
from infrastructure.connectors.google_drive.folder import is_drive_folder_id

logger = logging.getLogger(__name__)


def drive_oauth_ready(settings: Settings) -> bool:
    oauth = settings.google_oauth
    return bool(oauth.client_id and oauth.client_secret and oauth.redirect_uri)


def drive_connection_store(settings: Settings):
    from infrastructure.connectors.google_drive.oauth import GoogleOAuthConnectionStore

    return GoogleOAuthConnectionStore(settings.google_oauth.token_path)


def _state_store(settings: Settings):
    from infrastructure.connectors.google_drive.oauth import GoogleOAuthStateStore

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
        drive.folder_id is not None
        and is_drive_folder_id(drive.folder_id)
        and drive.service_account_file is not None
    )
    available = importlib.util.find_spec("googleapiclient") is not None
    connection = drive_connection_store(settings).load()
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
    setup_required = (
        connection is not None
        and not reauthorization_required
        and not connection.folders
        and not connection.files
    )
    if connection is None:
        connection_state = "disconnected"
    elif reauthorization_required:
        connection_state = "reauthorization_required"
    elif setup_required:
        connection_state = "setup_required"
    else:
        connection_state = "ready"
    return GoogleDriveStatus(
        configured=configured,
        available=available,
        connected=connection is not None,
        oauth_ready=drive_oauth_ready(settings),
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
        setup_required=setup_required,
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
        working = _container.resolve_catalog(
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
    if not drive_oauth_ready(settings):
        return _hub_redirect(settings, result="unconfigured")
    from infrastructure.connectors.google_drive.oauth import authorization_url

    store = state_store if state_store is not None else _state_store(settings)
    state = store.issue()
    return authorization_url(
        settings.google_oauth,
        state=state,
        include_drive_file="software-delivery" in settings.domain_tools.enabled_packs,
    )


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
    if not drive_oauth_ready(settings):
        return _hub_redirect(settings, result="error")
    from infrastructure.connectors.google_drive.oauth import (
        GoogleOAuthConnection,
        GoogleOAuthError,
        HttpGoogleOAuthGateway,
    )

    oauth_gateway = gateway if gateway is not None else HttpGoogleOAuthGateway(
        settings.google_oauth
    )
    tokens_store = (
        connection_store if connection_store is not None else drive_connection_store(settings)
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
                granted_scopes=grant.granted_scopes,
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
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
) -> None:
    """Revoke the stored refresh token, delete the local grant, and purge docs.

    Synced Google Drive catalog rows are removed from the catalog and vector store.

    Args:
        settings (Settings): Loaded environment settings.
        connection_store: Injected connection store for tests.
        gateway: Injected Google token gateway for tests.
        catalog (DocumentCatalog | None): Injected catalog for tests.
        catalog_factory (Callable[[], DocumentCatalog] | None): Lazy catalog.
        vector_store (VectorStore | None): Injected store for tests.
        vector_store_factory (Callable[[], VectorStore] | None): Lazy store.

    Raises:
        GoogleDriveNotConnectedError: No stored grant.
    """
    tokens_store = (
        connection_store if connection_store is not None else drive_connection_store(settings)
    )
    connection = tokens_store.load()
    if connection is None:
        raise GoogleDriveNotConnectedError("Google Drive is not connected")
    from infrastructure.connectors.google_drive.oauth import HttpGoogleOAuthGateway

    oauth_gateway = gateway if gateway is not None else HttpGoogleOAuthGateway(
        settings.google_oauth
    )
    oauth_gateway.revoke(connection.refresh_token)
    tokens_store.clear()
    purge_google_drive_docs(
        settings,
        catalog=catalog,
        catalog_factory=catalog_factory,
        vector_store=vector_store,
        vector_store_factory=vector_store_factory,
    )


def require_drive_grant(settings: Settings, *, connection_store=None):
    """Load a usable Hub Drive grant, or raise a typed connection error."""
    tokens_store = (
        connection_store if connection_store is not None else drive_connection_store(settings)
    )
    connection = tokens_store.load()
    if connection is None:
        raise GoogleDriveNotConnectedError("Google Drive is not connected")
    if connection.reauthorization_required:
        raise GoogleDriveReauthorizationRequiredError(
            "Google Drive authorization was revoked"
        )
    return tokens_store, connection


def require_drive_export_grant(settings: Settings, *, connection_store=None):
    """Require a Drive grant that includes ``drive.file`` for outbound writes.

    Missing ``drive.file`` is a local precondition — it raises without mutating
    a still-valid readonly grant.
    """
    from infrastructure.connectors.google_drive.oauth import DRIVE_FILE_SCOPE

    tokens_store, connection = require_drive_grant(
        settings, connection_store=connection_store
    )
    if DRIVE_FILE_SCOPE not in connection.granted_scopes:
        raise GoogleDriveReauthorizationRequiredError(
            "Google Drive authorization was revoked"
        )
    return tokens_store, connection


def mark_drive_reauth(tokens_store, error: BaseException) -> NoReturn:
    """Persist ``reauthorization_required`` and raise the typed Hub error."""
    tokens_store.mutate(
        lambda current: None
        if current is None
        else replace(current, reauthorization_required=True)
    )
    raise GoogleDriveReauthorizationRequiredError(
        "Google Drive authorization was revoked"
    ) from error


def purge_google_drive_docs(
    settings: Settings,
    *,
    source_ids: frozenset[str] | None = None,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
) -> None:
    """Delete Google Drive catalog+vector rows.

    When ``source_ids`` is None, every Drive row is removed. Otherwise only
    rows whose ``source_id`` is in ``source_ids`` are removed.
    """
    working = _container.resolve_catalog(
        settings, catalog=catalog, catalog_factory=catalog_factory
    )
    targets = [
        row
        for row in working.all()
        if row.reference.source_type == SourceType.GOOGLE_DRIVE
        and (source_ids is None or row.reference.source_id in source_ids)
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


def after_google_drive_document_deleted(settings: Settings, file_id: str) -> None:
    """Drop ``file_id`` from saved file roots after a Drive catalog delete."""
    drive_connection_store(settings).mutate(
        lambda current: None
        if current is None
        else replace(
            current,
            files=tuple(item for item in current.files if item.id != file_id),
        )
    )
