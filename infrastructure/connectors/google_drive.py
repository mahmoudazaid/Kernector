"""Google Drive KnowledgeConnector adapter."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Protocol

from google.auth.exceptions import RefreshError
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorUnavailableError,
)
from domain.knowledge import (
    ConnectorDocument,
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
    UploadPayload,
)
from domain.ports import DocumentExtractor
from infrastructure.config import GoogleDriveSettings
from infrastructure.documents.uploaded_files import (
    SUPPORTED_SUFFIXES,
    DocumentExtractionError,
    UploadedFileExtractor,
)

_SCOPES = ("https://www.googleapis.com/auth/drive.readonly",)
_GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
_LIST_FIELDS = (
    "nextPageToken,"
    "files(id,name,mimeType,version,md5Checksum,size,capabilities(canDownload))"
)
_RATE_LIMIT_REASONS = frozenset(
    {
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "quotaExceeded",
        "dailyLimitExceeded",
        "sharingRateLimitExceeded",
    }
)
_DOWNLOAD_CHUNK_SIZE = 256 * 1024

_MSG_AUTH = "Google Drive rejected the connector credentials or permissions."
_MSG_UNAVAILABLE = "Google Drive is temporarily unavailable."
_MSG_REQUEST_FAILED = "The Google Drive request failed."
_MSG_UNREADABLE = "A Google Drive file could not be read as text."
_MSG_TOO_LARGE = "A Google Drive file exceeded the configured size limit."
_MSG_CONFIG = "Google Drive connector configuration is invalid."
_MSG_CREDENTIALS = "Google Drive connector credentials could not be read."


class GoogleDriveConfigError(RuntimeError):
    """Drive connector settings are missing or the credential file is unusable."""


class DriveFiles(Protocol):
    """Subset of the Drive ``files`` resource used by this adapter."""

    def list(self, **kwargs: object) -> object: ...

    def get_media(self, *, fileId: str) -> object: ...

    def export_media(self, *, fileId: str, mimeType: str) -> object: ...


class MediaDownloader(Protocol):
    """Streaming media downloader that writes into a caller-supplied buffer."""

    def next_chunk(self) -> tuple[object, bool]: ...


DownloaderFactory = Callable[[BinaryIO, object], MediaDownloader]


class GoogleDriveConnector:
    """List and fetch supported files from one configured Drive folder.

    Args:
        settings (GoogleDriveSettings): Folder, page size, and optional credential path.
        max_upload_bytes (int): Maximum downloaded or exported payload size.
        files (DriveFiles | None): Injected Drive files resource. When omitted,
            a readonly Drive client is built from the service-account file.
        extractor (DocumentExtractor | None): Text extractor; defaults to the
            shared upload extractor.
        downloader_factory (DownloaderFactory | None): Builds a streaming
            downloader. Production uses ``MediaIoBaseDownload``.

    Raises:
        GoogleDriveConfigError: Folder ID is missing, or credentials cannot be used.
    """

    def __init__(
        self,
        settings: GoogleDriveSettings,
        *,
        max_upload_bytes: int,
        files: DriveFiles | None = None,
        extractor: DocumentExtractor | None = None,
        downloader_factory: DownloaderFactory | None = None,
    ) -> None:
        folder_id = settings.folder_id
        if folder_id is None or not folder_id.strip():
            raise GoogleDriveConfigError(_MSG_CONFIG)
        self._folder_id = folder_id.strip()
        self._page_size = settings.page_size
        self._max_upload_bytes = max_upload_bytes
        self._files = files if files is not None else _build_drive_files(settings)
        self._extractor = extractor or UploadedFileExtractor()
        self._downloader_factory = downloader_factory or _media_downloader

    def list_documents(self) -> Sequence[ConnectorDocument]:
        """Return supported direct children of the configured folder.

        Raises:
            ConnectorAuthError: Credentials or permissions were rejected.
            ConnectorUnavailableError: The provider is unreachable or throttling.
            ConnectorError: Listing failed or a supported entry was unusable.
        """
        documents: list[ConnectorDocument] = []
        page_token: str | None = None
        try:
            while True:
                request = self._files.list(
                    q=f"'{self._folder_id}' in parents and trashed = false",
                    spaces="drive",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    pageSize=self._page_size,
                    pageToken=page_token,
                    fields=_LIST_FIELDS,
                )
                payload = _execute(request)
                files = payload.get("files") if isinstance(payload, Mapping) else None
                if files is None:
                    files = ()
                if not isinstance(files, Sequence) or isinstance(files, (str, bytes)):
                    raise ConnectorError(_MSG_REQUEST_FAILED)
                for entry in files:
                    document = _document_from_file(entry)
                    if document is not None:
                        documents.append(document)
                next_token = payload.get("nextPageToken") if isinstance(payload, Mapping) else None
                if not next_token:
                    break
                if not isinstance(next_token, str):
                    raise ConnectorError(_MSG_REQUEST_FAILED)
                page_token = next_token
        except ConnectorError:
            raise
        except Exception as error:
            raise _map_google_error(error) from error
        return tuple(documents)

    def fetch_document(self, document: ConnectorDocument) -> SourceDocument:
        """Download or export ``document`` and normalize extractor metadata.

        Raises:
            ConnectorAuthError: Download was refused or credentials were rejected.
            ConnectorUnavailableError: The provider is unreachable or throttling.
            ConnectorError: Size, extraction, or other Drive failures.
        """
        mime_type = document.extra.get("mime_type", "")
        if document.extra.get("can_download") == "false":
            raise ConnectorAuthError(_MSG_AUTH)
        reported_size = _optional_size(document.extra.get("size"))
        if reported_size is not None and reported_size > self._max_upload_bytes:
            raise ConnectorError(_MSG_TOO_LARGE)
        try:
            if mime_type == _GOOGLE_DOC_MIME:
                request = self._files.export_media(
                    fileId=document.source_id,
                    mimeType="text/markdown",
                )
            else:
                request = self._files.get_media(fileId=document.source_id)
            content = self._download(request)
        except ConnectorError:
            raise
        except Exception as error:
            raise _map_google_error(error) from error
        payload_name = _payload_file_name(document.file_name, mime_type)
        try:
            extracted = self._extractor.extract(
                UploadPayload(file_name=payload_name, content=content),
                reference=document.reference,
            )
        except DocumentExtractionError as error:
            raise ConnectorError(_MSG_UNREADABLE) from error
        return _normalize_source(document, extracted, mime_type, content)

    def _download(self, request: object) -> bytes:
        buffer = BytesIO()
        downloader = self._downloader_factory(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
            if buffer.tell() > self._max_upload_bytes:
                raise ConnectorError(_MSG_TOO_LARGE)
        return buffer.getvalue()


def _media_downloader(buffer: BinaryIO, request: object) -> MediaDownloader:
    return MediaIoBaseDownload(
        buffer,
        request,
        chunksize=_DOWNLOAD_CHUNK_SIZE,
    )


def _build_drive_files(settings: GoogleDriveSettings) -> DriveFiles:
    path = settings.service_account_file
    if path is None:
        raise GoogleDriveConfigError(_MSG_CONFIG)
    try:
        credentials = service_account.Credentials.from_service_account_file(
            str(path),
            scopes=_SCOPES,
        )
        service = build(
            "drive",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )
        return service.files()
    except GoogleDriveConfigError:
        raise
    except Exception as error:
        raise GoogleDriveConfigError(_MSG_CREDENTIALS) from error


def _execute(request: object) -> Mapping[str, object]:
    execute = getattr(request, "execute", None)
    if not callable(execute):
        raise ConnectorError(_MSG_REQUEST_FAILED)
    payload = execute()
    if not isinstance(payload, Mapping):
        raise ConnectorError(_MSG_REQUEST_FAILED)
    return payload


def _document_from_file(entry: object) -> ConnectorDocument | None:
    if not isinstance(entry, Mapping):
        raise ConnectorError(_MSG_REQUEST_FAILED)
    mime_type = entry.get("mimeType")
    name = entry.get("name")
    if not _is_supported(name, mime_type):
        return None
    try:
        file_id = _require_entry_text(entry, "id")
        file_name = _require_entry_text(entry, "name")
        revision = _revision_from_file(entry)
    except ConnectorError:
        raise
    except Exception as error:
        raise ConnectorError(_MSG_REQUEST_FAILED) from error
    extra: dict[str, str] = {}
    if isinstance(mime_type, str) and mime_type:
        extra["mime_type"] = mime_type
    size = entry.get("size")
    if size is not None:
        extra["size"] = str(size)
    extra["can_download"] = (
        "true" if _can_download(entry) else "false"
    )
    checksum = entry.get("md5Checksum")
    if isinstance(checksum, str) and checksum:
        extra["md5_checksum"] = checksum
    return ConnectorDocument(
        reference=SourceReference(file_id, SourceType.GOOGLE_DRIVE),
        file_name=file_name,
        revision=revision,
        extra=extra,
    )


def _is_supported(name: object, mime_type: object) -> bool:
    if mime_type == _GOOGLE_DOC_MIME:
        return True
    if not isinstance(name, str):
        return False
    return Path(name).suffix.lower() in SUPPORTED_SUFFIXES


def _revision_from_file(entry: Mapping[str, object]) -> str:
    version = entry.get("version")
    if isinstance(version, str) and version.strip():
        return version
    if isinstance(version, int) and not isinstance(version, bool):
        return str(version)
    checksum = entry.get("md5Checksum")
    if isinstance(checksum, str) and checksum.strip():
        return checksum
    raise ConnectorError(_MSG_REQUEST_FAILED)


def _can_download(entry: Mapping[str, object]) -> bool:
    capabilities = entry.get("capabilities")
    if not isinstance(capabilities, Mapping):
        return True
    can_download = capabilities.get("canDownload")
    if can_download is False:
        return False
    return True


def _require_entry_text(entry: Mapping[str, object], field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConnectorError(_MSG_REQUEST_FAILED)
    return value


def _optional_size(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _payload_file_name(file_name: str, mime_type: str) -> str:
    if mime_type == _GOOGLE_DOC_MIME:
        suffix = Path(file_name).suffix.lower()
        if suffix not in {".md", ".markdown"}:
            return f"{file_name}.md"
    return file_name


def _normalize_source(
    document: ConnectorDocument,
    extracted: SourceDocument,
    mime_type: str,
    content: bytes,
) -> SourceDocument:
    preserved: dict[str, str] = {}
    page_count = extracted.metadata.extra.get("page_count")
    if page_count is not None:
        preserved["page_count"] = page_count
    return SourceDocument(
        SourceMetadata(
            reference=document.reference,
            title=Path(document.file_name).stem,
            provider="google_drive",
            content_format=extracted.metadata.content_format,
            extra={
                "file_name": document.file_name,
                "drive_file_id": document.source_id,
                "drive_mime_type": mime_type,
                "drive_revision": document.revision,
                "byte_size": str(len(content)),
                **preserved,
            },
        ),
        extracted.content,
    )


def _map_google_error(error: BaseException) -> ConnectorError:
    if isinstance(error, ConnectorError):
        return error
    if isinstance(error, RefreshError):
        return ConnectorAuthError(_MSG_AUTH)
    if isinstance(error, HttpError):
        return _map_http_error(error)
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return ConnectorUnavailableError(_MSG_UNAVAILABLE)
    return ConnectorError(_MSG_REQUEST_FAILED)


def _map_http_error(error: HttpError) -> ConnectorError:
    status = _http_status(error)
    if status == 401:
        return ConnectorAuthError(_MSG_AUTH)
    if status == 403:
        reasons = _http_reasons(error)
        if reasons & _RATE_LIMIT_REASONS:
            return ConnectorUnavailableError(_MSG_UNAVAILABLE)
        return ConnectorAuthError(_MSG_AUTH)
    if status in {408, 429} or (status is not None and status >= 500):
        return ConnectorUnavailableError(_MSG_UNAVAILABLE)
    return ConnectorError(_MSG_REQUEST_FAILED)


def _http_status(error: HttpError) -> int | None:
    raw = getattr(error.resp, "status", None)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _http_reasons(error: HttpError) -> set[str]:
    try:
        payload = json.loads(error.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    body = payload.get("error")
    if not isinstance(body, dict):
        return set()
    reasons: set[str] = set()
    errors = body.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, Mapping):
                reason = item.get("reason")
                if isinstance(reason, str):
                    reasons.add(reason)
    reason = body.get("reason")
    if isinstance(reason, str):
        reasons.add(reason)
    return reasons
