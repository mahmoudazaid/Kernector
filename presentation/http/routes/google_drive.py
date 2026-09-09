"""Versioned Google Drive connector routes."""

from application.errors import (
    GoogleDriveNotConnectedError,
    GoogleDriveReauthorizationRequiredError,
)
from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from composition import GoogleDriveSelectedItem, GoogleDriveStatus
from presentation.http.deps import (
    GoogleDriveBrowseDep,
    GoogleDriveDisconnectDep,
    GoogleDriveOAuthCallbackDep,
    GoogleDriveOAuthStartDep,
    GoogleDriveSelectionReadDep,
    GoogleDriveSelectionWriteDep,
    GoogleDriveStatusDep,
    GoogleDriveSyncDep,
)
from presentation.http.errors import problem_responses
from presentation.http.schemas import (
    GoogleDriveBrowseItemResponse,
    GoogleDriveBrowsePageResponse,
    GoogleDriveLastSyncResponse,
    GoogleDriveSelectedItemResponse,
    GoogleDriveSelectionResponse,
    GoogleDriveStatusResponse,
    GoogleDriveSyncResponse,
    google_drive_sync_response,
)

router = APIRouter(prefix="/api/v1", tags=["connectors"])


def _status_response(status: GoogleDriveStatus) -> GoogleDriveStatusResponse:
    last = status.last_sync
    return GoogleDriveStatusResponse(
        configured=status.configured,
        available=status.available,
        connected=status.connected,
        oauth_ready=status.oauth_ready,
        account_email=status.account_email,
        document_count=status.document_count,
        folder_count=status.folder_count,
        last_sync=(
            None
            if last is None
            else GoogleDriveLastSyncResponse(
                synced_at=last.synced_at,
                new_count=last.new_count,
                updated_count=last.updated_count,
                unchanged_count=last.unchanged_count,
                failed_count=last.failed_count,
            )
        ),
        reauthorization_required=status.reauthorization_required,
        setup_required=status.setup_required,
        connection_state=status.connection_state,
        sync_scope=status.sync_scope,
    )


@router.get(
    "/connectors/google-drive",
    responses=problem_responses(405, 500),
)
def google_drive_connector_status(
    status: GoogleDriveStatusDep,
) -> GoogleDriveStatusResponse:
    """Return presentation-safe Drive SA flags and user OAuth connection."""
    return _status_response(status)


@router.get(
    "/connectors/google-drive/oauth/start",
    responses=problem_responses(405, 500),
)
def google_drive_oauth_start(
    start: GoogleDriveOAuthStartDep,
) -> RedirectResponse:
    """Issue CSRF state and redirect the browser to Google, or back to the Hub."""
    return RedirectResponse(url=start(), status_code=302)


@router.get(
    "/connectors/google-drive/oauth/callback",
    responses=problem_responses(405, 500),
)
def google_drive_oauth_callback(
    complete: GoogleDriveOAuthCallbackDep,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Validate state, exchange the code server-side, and return to the Hub."""
    return RedirectResponse(
        url=complete(state, code, error),
        status_code=302,
    )


@router.post(
    "/connectors/google-drive/sync",
    responses=problem_responses(405, 409, 500, 502),
)
def google_drive_connector_sync(
    status: GoogleDriveStatusDep,
    sync: GoogleDriveSyncDep,
) -> GoogleDriveSyncResponse:
    """Synchronize Drive for the stored user OAuth grant."""
    if not status.connected:
        raise GoogleDriveNotConnectedError("Google Drive is not connected")
    if status.reauthorization_required:
        raise GoogleDriveReauthorizationRequiredError(
            "Google Drive authorization was revoked"
        )
    return google_drive_sync_response(sync())


@router.delete(
    "/connectors/google-drive",
    status_code=204,
    responses=problem_responses(405, 409, 500),
)
def google_drive_connector_disconnect(
    disconnect: GoogleDriveDisconnectDep,
) -> None:
    """Revoke and delete the stored user grant. Indexed documents stay."""
    disconnect()


@router.get(
    "/connectors/google-drive/items",
    responses=problem_responses(405, 409, 422, 500, 502),
)
def google_drive_connector_items(
    browse: GoogleDriveBrowseDep,
    parent_id: str | None = None,
    kind: str = "folders",
    query: str | None = None,
    page_token: str | None = None,
) -> GoogleDriveBrowsePageResponse:
    """List Drive folders or files for the content picker. No tokens on the wire."""
    page = browse(
        parent_id=parent_id,
        kind=kind,
        query=query,
        page_token=page_token,
    )
    return GoogleDriveBrowsePageResponse(
        items=[
            GoogleDriveBrowseItemResponse(
                id=item.id,
                name=item.name,
                kind=item.kind,
                mime_type=item.mime_type,
                supported=item.supported,
                modified_at=item.modified_at,
            )
            for item in page.items
        ],
        next_page_token=page.next_page_token,
    )


@router.get(
    "/connectors/google-drive/selection",
    responses=problem_responses(405, 409, 500),
)
def google_drive_connector_get_selection(
    load_selection: GoogleDriveSelectionReadDep,
) -> GoogleDriveSelectionResponse:
    """Return saved folder and file roots (Drive IDs and names only)."""
    selection = load_selection()
    return _selection_response(selection)


@router.put(
    "/connectors/google-drive/selection",
    responses=problem_responses(405, 409, 422, 500, 502),
)
def google_drive_connector_put_selection(
    body: GoogleDriveSelectionResponse,
    save_selection: GoogleDriveSelectionWriteDep,
) -> GoogleDriveSelectionResponse:
    """Validate access and atomically replace the saved Drive selection."""
    return _selection_response(
        save_selection(
            folders=tuple(
                GoogleDriveSelectedItem(id=item.id, name=item.name)
                for item in body.folders
            ),
            files=tuple(
                GoogleDriveSelectedItem(id=item.id, name=item.name)
                for item in body.files
            ),
        )
    )


def _selection_response(selection) -> GoogleDriveSelectionResponse:
    return GoogleDriveSelectionResponse(
        folders=[
            GoogleDriveSelectedItemResponse(id=item.id, name=item.name)
            for item in selection.folders
        ],
        files=[
            GoogleDriveSelectedItemResponse(id=item.id, name=item.name)
            for item in selection.files
        ],
    )
