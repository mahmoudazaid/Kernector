"""Google Drive KnowledgeConnector adapter."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Protocol

from google.auth.exceptions import (
    RefreshError,
    TimeoutError as GoogleAuthTimeoutError,
    TransportError,
)
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from httplib2 import HttpLib2Error

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
_FOLDER_MIME = "application/vnd.google-apps.folder"
_GOOGLE_APPS_PREFIX = "application/vnd.google-apps."
_FILE_FIELDS = (
    "id,name,mimeType,version,md5Checksum,size,modifiedTime,trashed,"
    "capabilities(canDownload)"
)
_LIST_FIELDS = f"nextPageToken,files({_FILE_FIELDS})"
_RATE_LIMIT_REASONS = frozenset(
    {
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "quotaExceeded",
        "dailyLimitExceeded",
        "sharingRateLimitExceeded",
    }
)
_MSG_AUTH = "Google Drive rejected the connector credentials or permissions."
_MSG_UNAVAILABLE = "Google Drive is temporarily unavailable."
_MSG_REQUEST_FAILED = "The Google Drive request failed."
_MSG_UNREADABLE = "A Google Drive file could not be read as text."
_MSG_TOO_LARGE = "A Google Drive file exceeded the configured size limit."
_MSG_CONFIG = "Google Drive connector configuration is invalid."
_MSG_CREDENTIALS = "Google Drive connector credentials could not be read."


class GoogleDriveConfigError(RuntimeError):
    """Drive connector settings are missing or the credential file is unusable."""


@dataclass(frozen=True, slots=True)
class DriveBrowseItem:
    """Presentation-safe Drive row. Identity is ``id``, never ``name``."""

    id: str
    name: str
    kind: str
    mime_type: str | None
    supported: bool
    modified_at: str | None


@dataclass(frozen=True, slots=True)
class DriveBrowsePage:
    """One page of browse results plus an opaque continuation token."""

    items: tuple[DriveBrowseItem, ...]
    next_page_token: str | None


class DriveFiles(Protocol):
    """Subset of the Drive ``files`` resource used by this adapter."""

    def list(self, **kwargs: object) -> object: ...

    def get(self, **kwargs: object) -> object: ...

    def get_media(self, *, fileId: str) -> object: ...

    def export_media(self, *, fileId: str, mimeType: str) -> object: ...


class MediaDownloader(Protocol):
    """Streaming media downloader that writes into a caller-supplied buffer."""

    def next_chunk(self) -> tuple[object, bool]: ...


DownloaderFactory = Callable[[BinaryIO, object], MediaDownloader]


class GoogleDriveConnector:
    """List and fetch supported Drive files from folder roots and exact IDs.

    CLI service-account sync uses one configured folder and **direct children
    only**. Knowledge Hub OAuth sync passes saved folder IDs with
    ``recursive=True`` plus exact file IDs. Folder roots stay durable: later
    syncs rediscover supported descendants. Missing, trashed, moved-out, or
    inaccessible items are omitted from the listing and are not deleted from
    the catalog.

    Args:
        settings (GoogleDriveSettings): Page size and optional SA folder/credentials.
        max_upload_bytes (int): Maximum downloaded or exported payload size.
        files (DriveFiles | None): Injected Drive files resource. When omitted,
            a readonly Drive client is built from the service-account file.
        extractor (DocumentExtractor | None): Text extractor; defaults to the
            shared upload extractor.
        downloader_factory (DownloaderFactory | None): Builds a streaming
            downloader. Production uses ``MediaIoBaseDownload``.
        folder_ids (Sequence[str] | None): Sync roots. ``None`` uses
            ``settings.folder_id`` when set.
        file_ids (Sequence[str]): Exact Drive file IDs to include once.
        recursive (bool): Walk folder descendants. Defaults to False (CLI).

    Raises:
        GoogleDriveConfigError: Folder ID is missing for the SA path, or
            credentials cannot be used.
    """

    def __init__(
        self,
        settings: GoogleDriveSettings,
        *,
        max_upload_bytes: int,
        files: DriveFiles | None = None,
        extractor: DocumentExtractor | None = None,
        downloader_factory: DownloaderFactory | None = None,
        folder_ids: Sequence[str] | None = None,
        file_ids: Sequence[str] = (),
        recursive: bool = False,
    ) -> None:
        resolved_folders = _normalized_ids(folder_ids)
        if folder_ids is None:
            configured = settings.folder_id
            if configured is not None and configured.strip():
                resolved_folders = (configured.strip(),)
        resolved_files = _normalized_ids(file_ids)
        if folder_ids is None and not resolved_folders and not resolved_files:
            raise GoogleDriveConfigError(_MSG_CONFIG)
        self._folder_ids = resolved_folders
        self._file_ids = resolved_files
        self._recursive = recursive
        self._page_size = settings.page_size
        self._max_upload_bytes = max_upload_bytes
        self._files = files if files is not None else _build_drive_files(settings)
        self._extractor = extractor or UploadedFileExtractor()
        self._downloader_factory = downloader_factory or (
            lambda buffer, request: MediaIoBaseDownload(
                buffer,
                request,
                chunksize=max_upload_bytes + 1,
            )
        )

    def list_documents(self) -> Sequence[ConnectorDocument]:
        """Return supported documents under saved folder roots and exact files.

        Folder listing is direct-child-only unless ``recursive`` is true.
        Duplicate Drive IDs (a file selected directly and also found under a
        folder) appear once. Trashed, inaccessible, and unsupported items are
        skipped; catalog rows are never deleted here.

        Raises:
            ConnectorAuthError: Credentials or permissions were rejected.
            ConnectorUnavailableError: The provider is unreachable or throttling.
            ConnectorError: Listing failed or a supported entry was unusable.
        """
        documents: dict[str, ConnectorDocument] = {}
        visited_folders: set[str] = set()
        try:
            for folder_id in self._folder_ids:
                self._collect_folder(folder_id, documents, visited_folders)
            for file_id in self._file_ids:
                if file_id in documents:
                    continue
                document = self._document_from_id(file_id)
                if document is not None:
                    documents[document.source_id] = document
        except ConnectorError:
            raise
        except Exception as error:
            raise _map_google_error(error) from error
        return tuple(documents.values())

    def list_items(
        self,
        *,
        parent_id: str = "root",
        kind: str = "folders",
        query: str | None = None,
        page_token: str | None = None,
    ) -> DriveBrowsePage:
        """Return one page of folders or files for the content picker.

        Args:
            parent_id (str): Drive folder ID to list. Ignored when ``query`` is set.
            kind (str): ``folders`` or ``files``.
            query (str | None): Case-insensitive name search across Drive.
            page_token (str | None): Opaque continuation token from a prior page.

        Raises:
            ConnectorAuthError: Credentials or permissions were rejected.
            ConnectorUnavailableError: The provider is unreachable or throttling.
            ConnectorError: The listing response was unusable.
        """
        try:
            request = self._files.list(
                q=_browse_query(parent_id=parent_id, kind=kind, query=query),
                spaces="drive",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                pageSize=self._page_size,
                pageToken=page_token,
                fields=_LIST_FIELDS,
                orderBy="folder,name",
            )
            payload = _execute(request)
        except ConnectorError:
            raise
        except Exception as error:
            raise _map_google_error(error) from error
        files = payload.get("files", ())
        if not isinstance(files, Sequence) or isinstance(files, (str, bytes)):
            raise ConnectorError(_MSG_REQUEST_FAILED)
        items = tuple(_browse_item_from_file(entry) for entry in files)
        next_token = payload.get("nextPageToken")
        if next_token is None or next_token == "":
            return DriveBrowsePage(items=items, next_page_token=None)
        if not isinstance(next_token, str):
            raise ConnectorError(_MSG_REQUEST_FAILED)
        return DriveBrowsePage(items=items, next_page_token=next_token)

    def get_item(self, item_id: str) -> DriveBrowseItem:
        """Load one Drive item by ID for selection validation.

        Raises:
            ConnectorAuthError: The user grant was rejected (typically 401).
            ConnectorUnavailableError: The provider is unreachable or throttling.
            ConnectorError: The item is missing, trashed, or unreadable.
        """
        try:
            entry = self._get_file(item_id)
        except ConnectorError:
            raise
        except Exception as error:
            raise _map_google_error(error) from error
        if entry.get("trashed") is True:
            raise ConnectorError(_MSG_REQUEST_FAILED)
        return _browse_item_from_file(entry)

    def _collect_folder(
        self,
        folder_id: str,
        documents: dict[str, ConnectorDocument],
        visited: set[str],
    ) -> None:
        if folder_id in visited:
            return
        visited.add(folder_id)
        child_folders: list[str] = []
        page_token: str | None = None
        try:
            while True:
                payload = self._list_children(folder_id, page_token)
                files = payload.get("files", ())
                if not isinstance(files, Sequence) or isinstance(files, (str, bytes)):
                    raise ConnectorError(_MSG_REQUEST_FAILED)
                for entry in files:
                    child_id = _optional_entry_text(entry, "id")
                    mime_type = entry.get("mimeType") if isinstance(entry, Mapping) else None
                    if mime_type == _FOLDER_MIME:
                        if self._recursive and child_id:
                            child_folders.append(child_id)
                        continue
                    document = _document_from_file(entry)
                    if document is not None and document.source_id not in documents:
                        documents[document.source_id] = document
                next_token = payload.get("nextPageToken")
                if not next_token:
                    break
                if not isinstance(next_token, str):
                    raise ConnectorError(_MSG_REQUEST_FAILED)
                page_token = next_token
            if self._recursive:
                for child_id in child_folders:
                    self._collect_folder(child_id, documents, visited)
        except HttpError as error:
            mapped = _map_google_error(error)
            status = _http_status(error)
            if status == 401 or isinstance(mapped, ConnectorUnavailableError):
                raise mapped from error
            if status in {403, 404}:
                return
            raise mapped from error

    def _list_children(self, folder_id: str, page_token: str | None) -> Mapping[str, object]:
        escaped = _escape_drive_query_value(folder_id)
        request = self._files.list(
            q=f"'{escaped}' in parents and trashed = false",
            spaces="drive",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            pageSize=self._page_size,
            pageToken=page_token,
            fields=_LIST_FIELDS,
        )
        return _execute(request)

    def _document_from_id(self, file_id: str) -> ConnectorDocument | None:
        try:
            entry = self._get_file(file_id)
        except HttpError as error:
            mapped = _map_google_error(error)
            status = _http_status(error)
            if status == 401 or isinstance(mapped, ConnectorUnavailableError):
                raise mapped from error
            if status in {403, 404}:
                return None
            raise mapped from error
        if entry.get("trashed") is True:
            return None
        if entry.get("mimeType") == _FOLDER_MIME:
            return None
        return _document_from_file(entry)

    def _get_file(self, file_id: str) -> Mapping[str, object]:
        request = self._files.get(
            fileId=file_id,
            supportsAllDrives=True,
            fields=_FILE_FIELDS,
        )
        return _execute(request)

    def fetch_document(self, document: ConnectorDocument) -> SourceDocument:
        """Download or export ``document`` and normalize extractor metadata.

        Raises:
            ConnectorAuthError: Credentials or permissions were rejected.
            ConnectorUnavailableError: The provider is unreachable or throttling.
            ConnectorError: Size, extraction, or other Drive failures.
        """
        mime_type = document.extra.get("mime_type", "")
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


def _normalized_ids(values: Sequence[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    return tuple(item.strip() for item in values if item.strip())


def _escape_drive_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _browse_query(*, parent_id: str, kind: str, query: str | None) -> str:
    parts = ["trashed = false"]
    if kind == "folders":
        parts.append(f"mimeType = '{_FOLDER_MIME}'")
    else:
        parts.append(f"mimeType != '{_FOLDER_MIME}'")
    stripped = query.strip() if isinstance(query, str) else ""
    if stripped:
        parts.append(f"name contains '{_escape_drive_query_value(stripped)}'")
    else:
        parts.append(f"'{_escape_drive_query_value(parent_id)}' in parents")
    return " and ".join(parts)


def _browse_item_from_file(entry: object) -> DriveBrowseItem:
    if not isinstance(entry, Mapping):
        raise ConnectorError(_MSG_REQUEST_FAILED)
    mime_type = entry.get("mimeType")
    mime_str = mime_type if isinstance(mime_type, str) and mime_type else None
    name = _require_entry_text(entry, "name")
    kind = "folder" if mime_str == _FOLDER_MIME else "file"
    modified = entry.get("modifiedTime")
    return DriveBrowseItem(
        id=_require_entry_text(entry, "id"),
        name=name,
        kind=kind,
        mime_type=mime_str,
        supported=kind == "folder" or _is_supported(name, mime_str),
        modified_at=modified if isinstance(modified, str) and modified else None,
    )


def _document_from_file(entry: object) -> ConnectorDocument | None:
    if not isinstance(entry, Mapping):
        raise ConnectorError(_MSG_REQUEST_FAILED)
    if entry.get("trashed") is True:
        return None
    mime_type = entry.get("mimeType")
    name = entry.get("name")
    if not _is_supported(name, mime_type):
        return None
    can_download = _can_download(entry)
    if not can_download:
        return None
    file_id = _require_entry_text(entry, "id")
    file_name = _require_entry_text(entry, "name")
    revision = _revision_from_file(entry)
    extra: dict[str, str] = {}
    if isinstance(mime_type, str) and mime_type:
        extra["mime_type"] = mime_type
    size = entry.get("size")
    if size is not None:
        extra["size"] = str(size)
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
    if isinstance(mime_type, str) and mime_type.startswith(_GOOGLE_APPS_PREFIX):
        return False
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
    modified = entry.get("modifiedTime")
    if isinstance(modified, str) and modified.strip():
        return modified
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


def _optional_entry_text(entry: object, field: str) -> str | None:
    if not isinstance(entry, Mapping):
        return None
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        return None
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
    if isinstance(error, RefreshError):
        return ConnectorAuthError(_MSG_AUTH)
    if isinstance(error, HttpError):
        return _map_http_error(error)
    if isinstance(
        error,
        (
            TimeoutError,
            ConnectionError,
            OSError,
            HttpLib2Error,
            TransportError,
            GoogleAuthTimeoutError,
        ),
    ):
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
