"""Google Drive connector construction and knowledge-base sync."""

from collections.abc import (
    Callable,
    Sequence,
)
from dataclasses import replace

from application.contracts import ConnectorSyncResponse
from application.errors import (
    ConfigurationError,
    GoogleDriveSelectionRequiredError,
)
from application.sync_connector import SyncConnectorDocuments
from composition import container as _container
from composition.errors import ConnectorSyncError
from composition.google_drive.connection import (
    mark_drive_reauth,
    require_drive_grant,
)
from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    VectorStoreError,
)
from domain.knowledge import SourceType
from domain.ports import (
    DocumentCatalog,
    KnowledgeConnector,
    VectorStore,
)
from infrastructure.catalog.errors import CatalogError
from infrastructure.config import Settings
from infrastructure.connectors.google_drive.folder import require_drive_folder_id


_DRIVE_CONFIG_MESSAGE = "Google Drive connector configuration is invalid."
_DRIVE_SYNC_MESSAGE = "The Google Drive connector sync failed."
_DRIVE_CLIENT_MISSING_MESSAGE = (
    "Google Drive client is not installed; run uv sync --extra google-drive."
)


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
    from infrastructure.connectors.google_drive.oauth import (
        GoogleOAuthError,
        build_oauth_drive_files,
    )

    try:
        from infrastructure.connectors.google_drive.connector import (
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

    tokens_store, connection = require_drive_grant(
        settings, connection_store=connection_store
    )
    if not connection.folders and not connection.files:
        raise GoogleDriveSelectionRequiredError(
            "Google Drive sync scope is not selected"
        )
    try:
        working_catalog = _container.resolve_catalog(
            settings, catalog=catalog, catalog_factory=catalog_factory
        )
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
            reconcile_missing=True,
        )
    except ConnectorSyncError as error:
        if isinstance(error.__cause__, ConnectorAuthError):
            mark_drive_reauth(tokens_store, error)
        raise
    new_count = result.ingested_count
    updated_count = result.updated_count
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
    folder_id = settings.google_drive.folder_id
    if folder_id is not None:
        try:
            require_drive_folder_id(folder_id)
        except ValueError as error:
            raise ConfigurationError(str(error)) from error
    try:
        from infrastructure.connectors.google_drive.connector import (
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
    reconcile_missing: bool = False,
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
        reconcile_missing (bool): When True, remove Google Drive catalog rows
            absent from the current listing (OAuth Hub sync).

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
            catalog = _container.build_document_catalog(settings)
        get_store = _container.lazy_vector_store(
            settings,
            vector_store=vector_store,
            vector_store_factory=vector_store_factory,
        )

        reconcile_kwargs: dict[str, object] = {}
        if reconcile_missing:
            # Empty prefix matches every source_id; scoped by source_type only.
            reconcile_kwargs = {
                "reconcile_missing": True,
                "reconcile_source_types": frozenset({SourceType.GOOGLE_DRIVE}),
                "reconcile_source_id_prefixes": frozenset({""}),
                "vector_store_factory": get_store,
            }

        return SyncConnectorDocuments(
            connector=connector,
            catalog=catalog,
            ingest_factory=lambda: _container.build_ingest_knowledge(
                settings,
                vector_store=get_store(),
            ),
            **reconcile_kwargs,
        ).execute()
    except ConnectorError as error:
        raise ConnectorSyncError(_DRIVE_SYNC_MESSAGE) from error
    except CatalogError as error:
        raise ConnectorSyncError(_DRIVE_SYNC_MESSAGE) from error
    except VectorStoreError as error:
        raise ConnectorSyncError(_DRIVE_SYNC_MESSAGE) from error
