"""Versioned Google Drive connector routes."""

from application.errors import GoogleDriveNotConfiguredError
from fastapi import APIRouter

from presentation.http.deps import GoogleDriveStatusDep, GoogleDriveSyncDep
from presentation.http.errors import problem_responses
from presentation.http.schemas import (
    GoogleDriveStatusResponse,
    GoogleDriveSyncResponse,
    google_drive_sync_response,
)

router = APIRouter(prefix="/api/v1", tags=["connectors"])


@router.get(
    "/connectors/google-drive",
    responses=problem_responses(405, 500),
)
def google_drive_connector_status(
    status: GoogleDriveStatusDep,
) -> GoogleDriveStatusResponse:
    """Return whether Drive env is present and the Google extra is importable."""
    return GoogleDriveStatusResponse(
        configured=status.configured,
        available=status.available,
    )


@router.post(
    "/connectors/google-drive/sync",
    responses=problem_responses(405, 409, 500, 502),
)
def google_drive_connector_sync(
    status: GoogleDriveStatusDep,
    sync: GoogleDriveSyncDep,
) -> GoogleDriveSyncResponse:
    """Synchronize the configured Drive folder into the knowledge base."""
    if not status.configured:
        raise GoogleDriveNotConfiguredError(
            "GOOGLE_DRIVE_FOLDER_ID or GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE "
            "is not configured"
        )
    return google_drive_sync_response(sync())
