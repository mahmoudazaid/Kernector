"""Google Drive connector DTOs returned to presentation."""

from dataclasses import dataclass


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
        setup_required (bool): Connected but no folders or files selected yet.
        connection_state (str): disconnected, ready, setup_required, or
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
