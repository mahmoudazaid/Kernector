"""Google Drive picker: browsing, folder creation, and the saved selection."""

import logging
import re
import threading
from collections.abc import (
    Callable,
    Iterable,
    Sequence,
)
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait,
)
from dataclasses import replace

from application.errors import (
    GoogleDriveNotConnectedError,
    GoogleDriveReauthorizationRequiredError,
    InputRejectedError,
)
from composition.errors import GoogleDriveConnectorError
from composition.google_drive import sync as _sync
from composition.google_drive.connection import (
    mark_drive_reauth,
    purge_google_drive_docs,
    require_drive_export_grant,
    require_drive_grant,
)
from composition.google_drive.models import (
    GoogleDriveBrowseItem,
    GoogleDriveBrowsePage,
    GoogleDriveSelectedItem,
    GoogleDriveSelection,
)
from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
)
from domain.ports import (
    DocumentCatalog,
    VectorStore,
)
from infrastructure.config import Settings
from infrastructure.connectors.google_drive.folder import DRIVE_ID_BODY

logger = logging.getLogger(__name__)


_DRIVE_REQUEST_MESSAGE = "The Google Drive request failed."
_DRIVE_ITEM_ID = re.compile(rf"^(root|{DRIVE_ID_BODY})$")
_DRIVE_SELECTION_ID = re.compile(rf"^(?!root$){DRIVE_ID_BODY}$")
_DRIVE_ITEM_NAME_MAX = 256
_DRIVE_QUERY_MAX = 200
_DRIVE_SELECTION_VALIDATE_WORKERS = 16
_DRIVE_VALIDATION_POOL = ThreadPoolExecutor(
    max_workers=_DRIVE_SELECTION_VALIDATE_WORKERS,
    thread_name_prefix="drive-validate",
)


_SELECTION_INACCESSIBLE_DETAIL = "A selected Drive item is not accessible."
_SELECTION_KIND_DETAIL = "A selected Drive item does not match the requested type."


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
    tokens_store, connection = require_drive_grant(
        settings, connection_store=connection_store
    )
    try:
        connector = _sync.build_google_drive_oauth_connector(
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
        mark_drive_reauth(tokens_store, error)
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


_DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"


def create_google_drive_folder(
    settings: Settings,
    *,
    name: str,
    parent_id: str | None = None,
    connection_store=None,
    files_factory=None,
) -> GoogleDriveBrowseItem:
    """Create a Drive folder under ``parent_id`` using the Hub OAuth grant.

    Args:
        settings (Settings): Loaded environment settings.
        name (str): Folder display name.
        parent_id (str | None): Parent folder ID. Defaults to My Drive (``root``).
        connection_store: Injected grant store for tests.
        files_factory: Injected ``(oauth_settings, refresh_token, scopes) -> files``
            factory for tests.

    Returns:
        GoogleDriveBrowseItem: The created folder row (id + name).

    Raises:
        GoogleDriveNotConnectedError: No stored grant.
        GoogleDriveReauthorizationRequiredError: Grant rejected or missing
            ``drive.file``.
        InputRejectedError: ``name`` or ``parent_id`` is invalid.
        GoogleDriveConnectorError: Create failed at the Google boundary.
    """
    if not isinstance(name, str):
        raise InputRejectedError("name must be a non-empty string.")
    stripped_name = name.strip()
    if not stripped_name:
        raise InputRejectedError("name must be a non-empty string.")
    if len(stripped_name) > _DRIVE_ITEM_NAME_MAX:
        raise InputRejectedError("name is too long.")
    resolved_parent = (
        "root" if parent_id is None or not parent_id.strip() else parent_id.strip()
    )
    if not _DRIVE_ITEM_ID.fullmatch(resolved_parent):
        raise InputRejectedError("parent_id must be a Drive folder ID.")

    tokens_store, connection = require_drive_export_grant(
        settings, connection_store=connection_store
    )
    from infrastructure.connectors.google_drive.oauth import (
        build_oauth_drive_files,
    )
    from infrastructure.connectors.google_drive.http_errors import (
        map_google_error,
    )

    factory = files_factory
    if factory is None:

        def factory(oauth_settings, refresh_token, scopes):
            return build_oauth_drive_files(
                oauth_settings,
                refresh_token=refresh_token,
                scopes=scopes,
            )

    try:
        files = factory(
            settings.google_oauth,
            connection.refresh_token,
            tuple(sorted(connection.granted_scopes)),
        )
        request = files.create(
            body={
                "name": stripped_name,
                "mimeType": _DRIVE_FOLDER_MIME,
                "parents": [resolved_parent],
            },
            fields="id,name,mimeType,modifiedTime",
            supportsAllDrives=True,
        )
        raw = request.execute()  # type: ignore[attr-defined]
    except ConnectorAuthError as error:
        mark_drive_reauth(tokens_store, error)
    except ConnectorError as error:
        raise GoogleDriveConnectorError(_DRIVE_REQUEST_MESSAGE) from error
    except Exception as error:  # noqa: BLE001 - map provider failures
        mapped = map_google_error(error)
        if isinstance(mapped, ConnectorAuthError):
            mark_drive_reauth(tokens_store, mapped)
        raise GoogleDriveConnectorError(_DRIVE_REQUEST_MESSAGE) from error

    if not isinstance(raw, dict):
        raise GoogleDriveConnectorError(_DRIVE_REQUEST_MESSAGE)
    folder_id = raw.get("id")
    folder_name = raw.get("name")
    if not isinstance(folder_id, str) or not folder_id.strip():
        raise GoogleDriveConnectorError(_DRIVE_REQUEST_MESSAGE)
    if not isinstance(folder_name, str) or not folder_name.strip():
        raise GoogleDriveConnectorError(_DRIVE_REQUEST_MESSAGE)
    modified = raw.get("modifiedTime")
    return GoogleDriveBrowseItem(
        id=folder_id.strip(),
        name=folder_name.strip(),
        kind="folder",
        mime_type=_DRIVE_FOLDER_MIME,
        supported=True,
        modified_at=modified if isinstance(modified, str) else None,
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
    _tokens_store, connection = require_drive_grant(
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
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
) -> GoogleDriveSelection:
    """Validate access and atomically replace the saved Drive selection.

    Dropped exact file selections are purged from the catalog immediately.
    Clearing every root purges all Google Drive documents. Folder drops that
    leave remaining roots are cleaned up by the next OAuth sync reconcile,
    which only runs after a complete listing (inaccessible selected roots raise).

    Args:
        settings (Settings): Loaded environment settings.
        folders (Sequence[GoogleDriveSelectedItem]): Folder roots by Drive ID.
        files (Sequence[GoogleDriveSelectedItem]): Exact file IDs.
        connection_store: Injected grant store for tests.
        connector_factory: Injected ``get_item`` factory for tests.
        catalog (DocumentCatalog | None): Injected catalog for tests.
        catalog_factory (Callable[[], DocumentCatalog] | None): Lazy catalog.
        vector_store (VectorStore | None): Injected store for tests.
        vector_store_factory (Callable[[], VectorStore] | None): Lazy store.

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
    tokens_store, connection = require_drive_grant(
        settings, connection_store=connection_store
    )
    previous_file_ids = frozenset(item.id for item in connection.files)
    try:
        resolved_folders, resolved_files = _validate_selection_items(
            settings,
            refresh_token=connection.refresh_token,
            folder_items=folder_items,
            file_items=file_items,
            connector_factory=connector_factory,
        )
    except ConnectorAuthError as error:
        mark_drive_reauth(tokens_store, error)
    except ConnectorError as error:
        raise InputRejectedError(_SELECTION_INACCESSIBLE_DETAIL) from error
    from infrastructure.connectors.google_drive.oauth import GoogleDriveSelectedItem as StoredItem

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
    new_file_ids = frozenset(item.id for item in resolved_files)
    if not resolved_folders and not resolved_files:
        purge_google_drive_docs(
            settings,
            catalog=catalog,
            catalog_factory=catalog_factory,
            vector_store=vector_store,
            vector_store_factory=vector_store_factory,
        )
    else:
        dropped_files = previous_file_ids - new_file_ids
        if dropped_files:
            purge_google_drive_docs(
                settings,
                source_ids=dropped_files,
                catalog=catalog,
                catalog_factory=catalog_factory,
                vector_store=vector_store,
                vector_store_factory=vector_store_factory,
            )
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
        return _sync.build_google_drive_oauth_connector(
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
                # Wait for any still-running lower-index jobs so the reported
                # rejection is the earliest selected item, not a race winner.
                min_error_index = min(index for index, _ in errors)
                pending_lower = [
                    future
                    for future, index in in_flight.items()
                    if index < min_error_index
                ]
                if pending_lower:
                    wait(pending_lower)
                    for future in list(in_flight):
                        index = in_flight[future]
                        if index >= min_error_index or not future.done():
                            continue
                        in_flight.pop(future)
                        try:
                            resolved[index] = future.result()
                        except BaseException as error:
                            errors.append((index, error))
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
