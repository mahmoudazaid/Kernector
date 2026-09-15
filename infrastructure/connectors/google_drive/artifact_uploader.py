"""OAuth Hub-user Google Drive artifact uploader."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from io import BytesIO
from typing import Protocol

from domain.artifacts import Artifact, ArtifactReceipt
from domain.errors import ConnectorAuthError, ConnectorError
from infrastructure.connectors.google_drive.folder import is_drive_folder_id
from infrastructure.connectors.google_drive.http_errors import (
    MSG_AUTH,
    MSG_REQUEST_FAILED,
    map_google_error,
)
from infrastructure.connectors.google_drive.oauth import (
    DRIVE_FILE_SCOPE,
    GoogleOAuthConnection,
    GoogleOAuthConnectionStore,
    GoogleOAuthSettings,
    build_oauth_drive_files,
)


class DriveFilesCreate(Protocol):
    """Subset of Drive ``files`` used for create uploads."""

    def create(self, **kwargs: object) -> object: ...


MediaUploadFactory = Callable[[bytes, str], object]
DriveFilesFactory = Callable[[GoogleOAuthSettings, str, Sequence[str]], DriveFilesCreate]
ConnectionLoader = Callable[[], GoogleOAuthConnection | None]


class GoogleDriveArtifactUploader:
    """Uploads artifacts into a caller-chosen Drive folder via Hub OAuth."""

    def __init__(
        self,
        *,
        oauth_settings: GoogleOAuthSettings,
        connection_store: GoogleOAuthConnectionStore,
        files_factory: DriveFilesFactory | None = None,
        media_factory: MediaUploadFactory | None = None,
        load_connection: ConnectionLoader | None = None,
    ) -> None:
        self._oauth_settings = oauth_settings
        self._connection_store = connection_store
        self._files_factory = files_factory or _default_files_factory
        self._media_factory = media_factory or _default_media_factory
        self._load_connection = load_connection or connection_store.load

    def upload(self, artifact: Artifact, *, parent_id: str) -> ArtifactReceipt:
        """Upload ``artifact`` into ``parent_id`` after a fresh ``drive.file`` preflight."""
        if not isinstance(parent_id, str) or not is_drive_folder_id(parent_id.strip()):
            raise ConnectorError(MSG_REQUEST_FAILED)
        folder_id = parent_id.strip()

        connection = self._load_connection()
        if connection is None:
            raise ConnectorAuthError(MSG_AUTH)
        if connection.reauthorization_required:
            raise ConnectorAuthError(MSG_AUTH)
        if DRIVE_FILE_SCOPE not in connection.granted_scopes:
            raise ConnectorAuthError(MSG_AUTH)

        try:
            media = self._media_factory(artifact.content, artifact.media_type)
            files = self._files_factory(
                self._oauth_settings,
                connection.refresh_token,
                tuple(sorted(connection.granted_scopes)),
            )
            request = files.create(
                body={
                    "name": artifact.file_name,
                    "parents": [folder_id],
                },
                media_body=media,
                fields="id,name",
                supportsAllDrives=True,
            )
            raw = request.execute()  # type: ignore[attr-defined]
        except ConnectorError:
            raise
        except Exception as error:  # noqa: BLE001 - map provider failures
            mapped = map_google_error(error)
            raise mapped from error

        if not isinstance(raw, dict):
            raise ConnectorError(MSG_REQUEST_FAILED)
        artifact_id = raw.get("id")
        file_name = raw.get("name")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ConnectorError(MSG_REQUEST_FAILED)
        if not isinstance(file_name, str) or not file_name.strip():
            raise ConnectorError(MSG_REQUEST_FAILED)
        return ArtifactReceipt(artifact_id=artifact_id, file_name=file_name)


def _default_media_factory(content: bytes, media_type: str) -> object:
    from googleapiclient.http import MediaIoBaseUpload

    return MediaIoBaseUpload(
        BytesIO(content),
        mimetype=media_type,
        resumable=False,
    )


def _default_files_factory(
    settings: GoogleOAuthSettings,
    refresh_token: str,
    scopes: Sequence[str],
) -> DriveFilesCreate:
    return build_oauth_drive_files(
        settings,
        refresh_token=refresh_token,
        scopes=scopes,
    )
