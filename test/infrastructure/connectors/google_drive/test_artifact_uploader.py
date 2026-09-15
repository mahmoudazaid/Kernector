"""Tests for GoogleDriveArtifactUploader — no live Google calls."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from domain.artifacts import Artifact
from domain.errors import ConnectorAuthError, ConnectorError
from infrastructure.config import GoogleOAuthSettings
from infrastructure.connectors.google_drive.artifact_uploader import (
    GoogleDriveArtifactUploader,
)
from infrastructure.connectors.google_drive.http_errors import MSG_AUTH
from infrastructure.connectors.google_drive.oauth import (
    DRIVE_FILE_SCOPE,
    DRIVE_READ_SCOPE,
    GoogleOAuthConnection,
    GoogleOAuthConnectionStore,
)


class _CreateRequest:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def execute(self) -> object:
        return self._payload


class _FakeFiles:
    def __init__(self, *, payload: object | None = None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._payload = payload if payload is not None else {"id": "file-1", "name": "out.md"}
        self._error = error

    def create(self, **kwargs: object) -> _CreateRequest:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return _CreateRequest(self._payload)


def _oauth_settings(tmp_path: Path) -> GoogleOAuthSettings:
    return GoogleOAuthSettings(
        client_id="client",
        client_secret="secret",
        redirect_uri="http://127.0.0.1/cb",
        frontend_redirect="http://localhost:3000/documents",
        token_path=tmp_path / "google-oauth-connection.json",
        state_path=tmp_path / "google-oauth-state.json",
        state_ttl_seconds=600,
    )


def _connection(**overrides: object) -> GoogleOAuthConnection:
    values = dict(
        refresh_token="1//refresh-secret",
        access_token="ya29.access-secret",
        account_email="ada@example.com",
        last_synced_at=None,
        last_sync_new=None,
        last_sync_updated=None,
        last_sync_unchanged=None,
        last_sync_failed=None,
        reauthorization_required=False,
        granted_scopes=frozenset({DRIVE_READ_SCOPE, DRIVE_FILE_SCOPE}),
    )
    values.update(overrides)
    return GoogleOAuthConnection(**values)  # type: ignore[arg-type]


def _artifact() -> Artifact:
    return Artifact(
        file_name="cases.md",
        media_type="text/markdown",
        content=b"# Cases\n",
    )


def _uploader(
    tmp_path: Path,
    *,
    files: _FakeFiles | None = None,
    media_factory=None,
    files_factory=None,
) -> tuple[GoogleDriveArtifactUploader, _FakeFiles]:
    fake_files = files if files is not None else _FakeFiles()
    store = GoogleOAuthConnectionStore(tmp_path / "conn.json")
    store.save(_connection())
    uploader = GoogleDriveArtifactUploader(
        oauth_settings=_oauth_settings(tmp_path),
        connection_store=store,
        files_factory=files_factory or (lambda *_a, **_k: fake_files),
        media_factory=media_factory or (lambda content, media_type: object()),
    )
    return uploader, fake_files


def test_upload_uses_media_metadata_and_shared_drive_flag(tmp_path: Path) -> None:
    files = _FakeFiles()
    media_calls: list[tuple[bytes, str]] = []
    factory_calls: list[tuple[str, tuple[str, ...]]] = []

    def media_factory(content: bytes, media_type: str) -> object:
        media_calls.append((content, media_type))
        return {"media": True}

    def files_factory(
        _settings: GoogleOAuthSettings,
        refresh_token: str,
        scopes: Sequence[str],
    ) -> _FakeFiles:
        factory_calls.append((refresh_token, tuple(scopes)))
        return files

    store = GoogleOAuthConnectionStore(tmp_path / "conn.json")
    store.save(_connection())
    uploader = GoogleDriveArtifactUploader(
        oauth_settings=_oauth_settings(tmp_path),
        connection_store=store,
        files_factory=files_factory,
        media_factory=media_factory,
    )

    receipt = uploader.upload(_artifact(), parent_id="folder-export-1")

    assert receipt.artifact_id == "file-1"
    assert receipt.file_name == "out.md"
    assert media_calls == [(b"# Cases\n", "text/markdown")]
    assert factory_calls[0][0] == "1//refresh-secret"
    assert DRIVE_FILE_SCOPE in factory_calls[0][1]
    call = files.calls[0]
    assert call["body"] == {"name": "cases.md", "parents": ["folder-export-1"]}
    assert call["media_body"] == {"media": True}
    assert call["fields"] == "id,name"
    assert call["supportsAllDrives"] is True


def test_invalid_parent_id_makes_zero_client_calls(tmp_path: Path) -> None:
    uploader, files = _uploader(tmp_path)
    with pytest.raises(ConnectorError):
        uploader.upload(_artifact(), parent_id="not a valid id!")
    assert files.calls == []


def test_missing_drive_file_scope_makes_zero_client_calls(tmp_path: Path) -> None:
    files = _FakeFiles()
    media_calls: list[tuple[bytes, str]] = []

    store = GoogleOAuthConnectionStore(tmp_path / "conn.json")
    store.save(_connection(granted_scopes=frozenset({DRIVE_READ_SCOPE})))
    uploader = GoogleDriveArtifactUploader(
        oauth_settings=_oauth_settings(tmp_path),
        connection_store=store,
        files_factory=lambda *_a, **_k: files,
        media_factory=lambda content, media_type: media_calls.append((content, media_type)),
    )

    with pytest.raises(ConnectorAuthError, match=MSG_AUTH):
        uploader.upload(_artifact(), parent_id="folder-export-1")
    assert files.calls == []
    assert media_calls == []


def test_missing_connection_makes_zero_client_calls(tmp_path: Path) -> None:
    files = _FakeFiles()
    store = GoogleOAuthConnectionStore(tmp_path / "conn.json")
    uploader = GoogleDriveArtifactUploader(
        oauth_settings=_oauth_settings(tmp_path),
        connection_store=store,
        files_factory=lambda *_a, **_k: files,
        media_factory=lambda *_a, **_k: None,
    )
    with pytest.raises(ConnectorAuthError):
        uploader.upload(_artifact(), parent_id="folder-export-1")
    assert files.calls == []


def test_fresh_connection_load_sees_scopes_granted_after_construction(
    tmp_path: Path,
) -> None:
    files = _FakeFiles()
    store = GoogleOAuthConnectionStore(tmp_path / "conn.json")
    store.save(_connection(granted_scopes=frozenset({DRIVE_READ_SCOPE})))
    uploader = GoogleDriveArtifactUploader(
        oauth_settings=_oauth_settings(tmp_path),
        connection_store=store,
        files_factory=lambda *_a, **_k: files,
        media_factory=lambda content, media_type: object(),
    )
    with pytest.raises(ConnectorAuthError):
        uploader.upload(_artifact(), parent_id="folder-export-1")

    store.save(_connection())
    receipt = uploader.upload(_artifact(), parent_id="folder-export-1")
    assert receipt.artifact_id == "file-1"
    assert len(files.calls) == 1


def test_blank_response_id_is_connector_error(tmp_path: Path) -> None:
    files = _FakeFiles(payload={"id": "  ", "name": "out.md"})
    store = GoogleOAuthConnectionStore(tmp_path / "conn.json")
    store.save(_connection())
    uploader = GoogleDriveArtifactUploader(
        oauth_settings=_oauth_settings(tmp_path),
        connection_store=store,
        files_factory=lambda *_a, **_k: files,
        media_factory=lambda *_a, **_k: object(),
    )
    with pytest.raises(ConnectorError):
        uploader.upload(_artifact(), parent_id="folder-export-1")


def test_provider_error_message_is_sanitized(tmp_path: Path) -> None:
    class _Boom(Exception):
        pass

    files = _FakeFiles(error=_Boom("raw provider body with token ya29.x"))
    store = GoogleOAuthConnectionStore(tmp_path / "conn.json")
    store.save(_connection())
    uploader = GoogleDriveArtifactUploader(
        oauth_settings=_oauth_settings(tmp_path),
        connection_store=store,
        files_factory=lambda *_a, **_k: files,
        media_factory=lambda *_a, **_k: object(),
    )
    with pytest.raises(ConnectorError) as raised:
        uploader.upload(_artifact(), parent_id="folder-export-1")
    assert "ya29" not in str(raised.value)
    assert "folder-export-1" not in str(raised.value)
    assert isinstance(raised.value.__cause__, _Boom)


def test_auth_message_does_not_leak_parent_id(tmp_path: Path) -> None:
    assert "secret-folder-id" not in MSG_AUTH
