"""Google Drive connector listing, download, metadata, and error mapping."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO

import pytest
from google.auth.exceptions import RefreshError, TimeoutError as GoogleAuthTimeoutError, TransportError
from googleapiclient.errors import HttpError
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
from infrastructure.config import GoogleDriveSettings
from infrastructure.connectors.google_drive import (
    GoogleDriveConfigError,
    GoogleDriveConnector,
)
from test.log_record import flatten_log_record

SECRET = "DRIVE-SECRET-TOKEN-LEAK"
GOOGLE_DOC = "application/vnd.google-apps.document"
FOLDER = "folder-123"


class FakeListRequest:
    def __init__(self, payload: object | None = None, error: BaseException | None = None) -> None:
        self._payload = payload
        self._error = error

    def execute(self) -> object:
        if self._error is not None:
            raise self._error
        return self._payload


class FakeDriveFiles:
    def __init__(
        self,
        pages: Sequence[dict[str, object]] | None = None,
        *,
        list_error: BaseException | None = None,
        media_error: BaseException | None = None,
    ) -> None:
        self._pages = list(pages or ())
        self._index = 0
        self.list_error = list_error
        self.media_error = media_error
        self.list_calls: list[dict[str, object]] = []
        self.get_media_ids: list[str] = []
        self.export_calls: list[tuple[str, str]] = []

    def list(self, **kwargs: object) -> FakeListRequest:
        self.list_calls.append(dict(kwargs))
        if self.list_error is not None:
            return FakeListRequest(error=self.list_error)
        if self._index >= len(self._pages):
            return FakeListRequest({"files": []})
        page = self._pages[self._index]
        self._index += 1
        return FakeListRequest(page)

    def get_media(self, *, fileId: str) -> object:
        self.get_media_ids.append(fileId)
        if self.media_error is not None:
            raise self.media_error
        return SimpleNamespace(kind="get_media", fileId=fileId)

    def export_media(self, *, fileId: str, mimeType: str) -> object:
        self.export_calls.append((fileId, mimeType))
        if self.media_error is not None:
            raise self.media_error
        return SimpleNamespace(kind="export_media", fileId=fileId, mimeType=mimeType)


class FakeDownloader:
    def __init__(self, buffer: BinaryIO, chunks: Sequence[bytes]) -> None:
        self._buffer = buffer
        self._chunks = list(chunks)
        self.calls = 0

    def next_chunk(self) -> tuple[object, bool]:
        self.calls += 1
        if self.calls > len(self._chunks):
            return None, True
        self._buffer.write(self._chunks[self.calls - 1])
        return None, self.calls >= len(self._chunks)


class RecordingExtractor:
    def __init__(
        self,
        *,
        content: str = "extracted text",
        extra: dict[str, str] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.content = content
        self.extra = extra or {
            "file_name": "tmp.md",
            "modified_at": "2026-01-01T00:00:00+00:00",
            "page_count": "3",
        }
        self.error = error
        self.payloads: list[UploadPayload] = []

    def extract(
        self, payload: UploadPayload, *, reference: SourceReference
    ) -> SourceDocument:
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error
        return SourceDocument(
            SourceMetadata(
                reference,
                title="tmp",
                provider="upload",
                content_format="markdown",
                extra=self.extra,
            ),
            self.content,
        )


def _http_error(status: int, body: dict[str, object] | None = None) -> HttpError:
    payload = body or {
        "error": {"message": SECRET, "errors": [{"reason": "forbidden"}]}
    }
    resp = SimpleNamespace(status=status, reason="error")
    return HttpError(resp, json.dumps(payload).encode("utf-8"))


def _settings(**overrides: object) -> GoogleDriveSettings:
    values: dict[str, object] = {
        "service_account_file": Path("/unused/sa.json"),
        "folder_id": FOLDER,
        "page_size": 100,
    }
    values.update(overrides)
    return GoogleDriveSettings(**values)  # type: ignore[arg-type]


def _connector(
    files: FakeDriveFiles,
    *,
    chunks: Sequence[bytes] = (b"hello",),
    extractor: RecordingExtractor | None = None,
    max_upload_bytes: int = 1024,
    settings: GoogleDriveSettings | None = None,
    downloaders: list[FakeDownloader] | None = None,
) -> GoogleDriveConnector:
    caught = downloaders if downloaders is not None else []

    def factory(buffer: BinaryIO, request: object) -> FakeDownloader:
        downloader = FakeDownloader(buffer, chunks)
        caught.append(downloader)
        return downloader

    return GoogleDriveConnector(
        settings or _settings(),
        max_upload_bytes=max_upload_bytes,
        files=files,
        extractor=extractor or RecordingExtractor(),
        downloader_factory=factory,
    )


def _file(
    file_id: str,
    name: str,
    *,
    mime_type: str = "text/plain",
    version: object = "1",
    md5: str | None = "abc",
    size: object | None = "12",
    can_download: bool | None = True,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": file_id,
        "name": name,
        "mimeType": mime_type,
    }
    if version is not None:
        entry["version"] = version
    if md5 is not None:
        entry["md5Checksum"] = md5
    if size is not None:
        entry["size"] = size
    if can_download is not None:
        entry["capabilities"] = {"canDownload": can_download}
    return entry


def test_missing_folder_id_raises_config_error_without_path() -> None:
    with pytest.raises(GoogleDriveConfigError, match="configuration is invalid") as raised:
        GoogleDriveConnector(
            GoogleDriveSettings(service_account_file=Path("/secret/sa.json")),
            max_upload_bytes=100,
            files=FakeDriveFiles(),
        )
    assert "/secret/sa.json" not in str(raised.value)


def test_unreadable_credentials_raise_config_error_without_path_or_body(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sa.json"
    path.write_text(f'{{"private_key": "{SECRET}"}}', encoding="utf-8")
    with pytest.raises(GoogleDriveConfigError) as raised:
        GoogleDriveConnector(
            GoogleDriveSettings(service_account_file=path, folder_id=FOLDER),
            max_upload_bytes=100,
        )
    message = str(raised.value)
    assert SECRET not in message
    assert str(path) not in message
    assert "could not be read" in message


def test_list_follows_two_pages_and_shared_drive_flags() -> None:
    files = FakeDriveFiles(
        [
            {
                "nextPageToken": "page-2",
                "files": [_file("a", "a.txt")],
            },
            {"files": [_file("b", "b.md", version="9")]},
        ]
    )
    documents = _connector(files).list_documents()
    assert [document.source_id for document in documents] == ["a", "b"]
    assert documents[0].reference.source_type == SourceType.GOOGLE_DRIVE
    assert documents[1].revision == "9"
    assert len(files.list_calls) == 2
    first, second = files.list_calls
    assert first["q"] == f"'{FOLDER}' in parents and trashed = false"
    assert first["spaces"] == "drive"
    assert first["supportsAllDrives"] is True
    assert first["includeItemsFromAllDrives"] is True
    assert first["pageSize"] == 100
    assert first.get("pageToken") is None
    assert "files(id" in str(first["fields"])
    assert second["pageToken"] == "page-2"


def test_list_includes_supported_binaries_and_google_docs() -> None:
    files = FakeDriveFiles(
        [
            {
                "files": [
                    _file("txt", "notes.txt"),
                    _file("md", "guide.md"),
                    _file("markdown", "spec.markdown"),
                    _file("pdf", "doc.pdf", mime_type="application/pdf"),
                    _file("gdoc", "Spec", mime_type=GOOGLE_DOC, md5=None, size=None),
                ]
            }
        ]
    )
    documents = _connector(files).list_documents()
    assert [document.file_name for document in documents] == [
        "notes.txt",
        "guide.md",
        "spec.markdown",
        "doc.pdf",
        "Spec",
    ]
    google_doc = documents[-1]
    assert google_doc.extra["mime_type"] == GOOGLE_DOC
    assert "size" not in google_doc.extra


def test_list_omits_unsupported_types() -> None:
    files = FakeDriveFiles(
        [
            {
                "files": [
                    _file("folder", "Child", mime_type="application/vnd.google-apps.folder"),
                    _file("sheet", "Sheet", mime_type="application/vnd.google-apps.spreadsheet"),
                    _file("slide", "Deck", mime_type="application/vnd.google-apps.presentation"),
                    _file("shortcut", "Link", mime_type="application/vnd.google-apps.shortcut"),
                    _file("png", "pic.png", mime_type="image/png"),
                    _file(
                        "sheet-txt",
                        "budget.txt",
                        mime_type="application/vnd.google-apps.spreadsheet",
                    ),
                    _file("ok", "ok.txt"),
                ]
            }
        ]
    )
    documents = _connector(files).list_documents()
    assert [document.source_id for document in documents] == ["ok"]


def test_list_omits_undownloadable_blob_files() -> None:
    files = FakeDriveFiles(
        [{"files": [_file("blocked", "secret.txt", can_download=False)]}]
    )
    documents = _connector(files).list_documents()
    assert documents == ()


def test_list_keeps_google_docs_when_can_download_is_false() -> None:
    files = FakeDriveFiles(
        [
            {
                "files": [
                    _file(
                        "gdoc",
                        "Spec",
                        mime_type=GOOGLE_DOC,
                        md5=None,
                        size=None,
                        can_download=False,
                    )
                ]
            }
        ]
    )
    documents = _connector(files).list_documents()
    assert [document.source_id for document in documents] == ["gdoc"]


def test_revision_prefers_version_over_checksum() -> None:
    files = FakeDriveFiles(
        [
            {
                "files": [
                    _file("renamed", "new-name.txt", version="7", md5="same-checksum")
                ]
            }
        ]
    )
    documents = _connector(files).list_documents()
    assert documents[0].revision == "7"
    assert documents[0].extra["md5_checksum"] == "same-checksum"


def test_revision_falls_back_to_checksum_when_version_missing() -> None:
    files = FakeDriveFiles(
        [{"files": [_file("only-md5", "a.txt", version=None, md5="deadbeef")]}]
    )
    documents = _connector(files).list_documents()
    assert documents[0].revision == "deadbeef"


def test_malformed_supported_entry_raises_safe_connector_error() -> None:
    files = FakeDriveFiles(
        [{"files": [{"name": "broken.txt", "mimeType": "text/plain"}]}]
    )
    with pytest.raises(ConnectorError, match="request failed") as raised:
        _connector(files).list_documents()
    assert "KeyError" not in str(raised.value)
    assert SECRET not in str(raised.value)


def test_fetch_blob_downloads_and_normalizes_metadata() -> None:
    listed = ConnectorDocument(
        reference=SourceReference("file-1", SourceType.GOOGLE_DRIVE),
        file_name="guide.md",
        revision="4",
        extra={"mime_type": "text/markdown", "size": "5", "can_download": "true"},
    )
    files = FakeDriveFiles()
    extractor = RecordingExtractor(content="# Guide")
    document = _connector(
        files, chunks=(b"hello",), extractor=extractor
    ).fetch_document(listed)
    assert files.get_media_ids == ["file-1"]
    assert files.export_calls == []
    assert document.reference == listed.reference
    assert document.metadata.provider == "google_drive"
    assert document.metadata.title == "guide"
    assert document.metadata.content_format == "markdown"
    extra = document.metadata.extra
    assert extra["file_name"] == "guide.md"
    assert extra["drive_file_id"] == "file-1"
    assert extra["drive_mime_type"] == "text/markdown"
    assert extra["drive_revision"] == "4"
    assert extra["byte_size"] == "5"
    assert extra["page_count"] == "3"
    assert "modified_at" not in extra
    assert extra.get("provider") != "upload"
    assert document.content == "# Guide"


def test_fetch_google_doc_exports_markdown() -> None:
    listed = ConnectorDocument(
        reference=SourceReference("gdoc-1", SourceType.GOOGLE_DRIVE),
        file_name="Spec",
        revision="2",
        extra={"mime_type": GOOGLE_DOC, "can_download": "true"},
    )
    files = FakeDriveFiles()
    extractor = RecordingExtractor(content="exported")
    document = _connector(
        files, chunks=(b"# Spec\n",), extractor=extractor
    ).fetch_document(listed)
    assert files.export_calls == [("gdoc-1", "text/markdown")]
    assert files.get_media_ids == []
    assert extractor.payloads[0].file_name == "Spec.md"
    assert document.metadata.provider == "google_drive"
    assert document.metadata.extra["file_name"] == "Spec"


def test_size_preflight_skips_media_and_extractor() -> None:
    listed = ConnectorDocument(
        reference=SourceReference("big", SourceType.GOOGLE_DRIVE),
        file_name="big.txt",
        revision="1",
        extra={"mime_type": "text/plain", "size": "200", "can_download": "true"},
    )
    files = FakeDriveFiles()
    extractor = RecordingExtractor()
    with pytest.raises(ConnectorError, match="size limit"):
        _connector(
            files, extractor=extractor, max_upload_bytes=100
        ).fetch_document(listed)
    assert files.get_media_ids == []
    assert extractor.payloads == []


def test_streaming_aborts_as_soon_as_limit_is_exceeded() -> None:
    listed = ConnectorDocument(
        reference=SourceReference("stream", SourceType.GOOGLE_DRIVE),
        file_name="a.txt",
        revision="1",
        extra={"mime_type": "text/plain", "can_download": "true"},
    )
    files = FakeDriveFiles()
    downloaders: list[FakeDownloader] = []
    with pytest.raises(ConnectorError, match="size limit"):
        _connector(
            files,
            chunks=(b"aaaa", b"bbbb", b"cccc"),
            max_upload_bytes=6,
            downloaders=downloaders,
        ).fetch_document(listed)
    assert downloaders[0].calls == 2
    assert files.get_media_ids == ["stream"]


def test_download_permission_refusal_is_auth_error() -> None:
    listed = ConnectorDocument(
        reference=SourceReference("blocked", SourceType.GOOGLE_DRIVE),
        file_name="a.txt",
        revision="1",
        extra={"mime_type": "text/plain", "can_download": "false"},
    )
    files = FakeDriveFiles()
    with pytest.raises(ConnectorAuthError, match="credentials or permissions"):
        _connector(files).fetch_document(listed)
    assert files.get_media_ids == []


def test_extraction_failure_is_safe_connector_error() -> None:
    from infrastructure.documents.uploaded_files import UnreadableDocumentError

    listed = ConnectorDocument(
        reference=SourceReference("bad", SourceType.GOOGLE_DRIVE),
        file_name="a.txt",
        revision="1",
        extra={"mime_type": "text/plain", "can_download": "true"},
    )
    extractor = RecordingExtractor(error=UnreadableDocumentError(SECRET))
    with pytest.raises(ConnectorError, match="could not be read as text") as raised:
        _connector(FakeDriveFiles(), extractor=extractor).fetch_document(listed)
    assert SECRET not in str(raised.value)
    assert raised.value.__cause__ is extractor.error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_http_error(401), ConnectorAuthError),
        (_http_error(403, {"error": {"errors": [{"reason": "insufficientFilePermissions"}], "message": SECRET}}), ConnectorAuthError),
        (_http_error(403, {"error": {"errors": [{"reason": "rateLimitExceeded"}], "message": SECRET}}), ConnectorUnavailableError),
        (_http_error(429), ConnectorUnavailableError),
        (_http_error(503), ConnectorUnavailableError),
        (TimeoutError(SECRET), ConnectorUnavailableError),
        (HttpLib2Error(SECRET), ConnectorUnavailableError),
        (TransportError(SECRET), ConnectorUnavailableError),
        (GoogleAuthTimeoutError(SECRET), ConnectorUnavailableError),
        (RefreshError(SECRET), ConnectorAuthError),
    ],
)
def test_google_failures_map_to_safe_domain_errors(
    error: BaseException, expected: type[ConnectorError]
) -> None:
    files = FakeDriveFiles(list_error=error)
    with pytest.raises(expected) as raised:
        _connector(files).list_documents()
    message = str(raised.value)
    assert SECRET not in message
    assert "rateLimitExceeded" not in message
    assert raised.value.__cause__ is error


def test_secret_marker_never_reaches_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    files = FakeDriveFiles(list_error=_http_error(401))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ConnectorAuthError):
            _connector(files).list_documents()
    log_text = "\n".join(flatten_log_record(record) for record in caplog.records)
    assert SECRET not in log_text
    assert SECRET not in caplog.text
