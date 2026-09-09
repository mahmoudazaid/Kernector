"""Server-side Google user OAuth for the Drive connector.

Tokens stay on disk. This module never logs codes, tokens, or client secrets.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import secrets
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from infrastructure.config import GoogleOAuthSettings

_LOG = logging.getLogger(__name__)
_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
_ABOUT_ENDPOINT = "https://www.googleapis.com/drive/v3/about?fields=user(emailAddress)"
_REDACTED = "***"


class GoogleOAuthError(RuntimeError):
    """The Google OAuth token endpoint or revoke call failed."""


@dataclass(frozen=True, slots=True)
class GoogleDriveSelectedItem:
    """Stable Drive identity plus a display name. Name is never an identifier."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class GoogleOAuthGrant:
    """Tokens returned by a successful authorization-code exchange."""

    access_token: str
    refresh_token: str


@dataclass(frozen=True, slots=True)
class GoogleOAuthConnection:
    """Persisted user grant plus presentation metadata (no secrets in repr)."""

    refresh_token: str
    access_token: str | None
    account_email: str | None
    folder_count: int
    last_synced_at: str | None
    last_sync_new: int | None
    last_sync_updated: int | None
    last_sync_unchanged: int | None
    last_sync_failed: int | None
    reauthorization_required: bool
    folders: tuple[GoogleDriveSelectedItem, ...] = ()
    files: tuple[GoogleDriveSelectedItem, ...] = ()

    def __repr__(self) -> str:
        return (
            "GoogleOAuthConnection("
            f"refresh_token={_REDACTED!r}, access_token={_REDACTED!r}, "
            f"account_email={self.account_email!r}, folder_count={self.folder_count}, "
            f"folders={len(self.folders)}, files={len(self.files)}, "
            f"last_synced_at={self.last_synced_at!r}, "
            f"reauthorization_required={self.reauthorization_required})"
        )


class GoogleOAuthStateStore:
    """Single-use CSRF ``state`` values with a TTL."""

    def __init__(self, path: Path, *, ttl_seconds: int) -> None:
        self._path = path
        self._ttl_seconds = ttl_seconds

    def issue(self) -> str:
        """Create and persist a new single-use state token."""
        token = secrets.token_urlsafe(32)
        with ExclusiveLock(self._path):
            items = self._read()
            now = time.time()
            items = {
                key: exp
                for key, exp in items.items()
                if isinstance(exp, (int, float)) and exp > now
            }
            items[token] = now + self._ttl_seconds
            self._write(items)
        return token

    def consume(self, token: str | None) -> bool:
        """Return True once for a valid unexpired token; reject replays."""
        if not token:
            return False
        with ExclusiveLock(self._path):
            items = self._read()
            expiry = items.pop(token, None)
            if expiry is None:
                return False
            self._write(items)
            return isinstance(expiry, (int, float)) and expiry >= time.time()

    def _read(self) -> dict[str, float]:
        if not self._path.is_file():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        parsed: dict[str, float] = {}
        for key, value in raw.items():
            if isinstance(key, str) and isinstance(value, (int, float)):
                parsed[key] = float(value)
        return parsed

    def _write(self, items: dict[str, float]) -> None:
        _atomic_write_json(self._path, items)


class GoogleOAuthConnectionStore:
    """JSON file store for the single-workspace user Drive grant."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> GoogleOAuthConnection | None:
        """Return the stored grant, or None when disconnected."""
        return self._load_unlocked()

    def save(self, connection: GoogleOAuthConnection) -> None:
        """Persist the grant. Overwrites the previous connection."""
        self.mutate(lambda _current: connection)

    def clear(self) -> None:
        """Delete the stored grant under the same lock as ``save``."""
        self.mutate(lambda _current: None)

    def mutate(
        self,
        mutator: Callable[
            [GoogleOAuthConnection | None], GoogleOAuthConnection | None
        ],
    ) -> GoogleOAuthConnection | None:
        """Re-read, apply ``mutator``, and persist under the exclusive lock.

        ``mutator`` receives the current grant (or ``None``) and returns the next
        grant, or ``None`` to delete it. Callers that loaded earlier must merge
        through this method so a concurrent selection change or disconnect is
        not overwritten.
        """
        with ExclusiveLock(self._path):
            next_value = mutator(self._load_unlocked())
            if next_value is None:
                try:
                    self._path.unlink()
                except FileNotFoundError:
                    pass
                return None
            _atomic_write_json(self._path, _connection_payload(next_value))
            return next_value

    def _load_unlocked(self) -> GoogleOAuthConnection | None:
        if not self._path.is_file():
            return None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        refresh = raw.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            return None
        return GoogleOAuthConnection(
            refresh_token=refresh,
            access_token=_optional_str(raw.get("access_token")),
            account_email=_optional_str(raw.get("account_email")),
            folder_count=_optional_int(raw.get("folder_count")) or 0,
            last_synced_at=_optional_str(raw.get("last_synced_at")),
            last_sync_new=_optional_int(raw.get("last_sync_new")),
            last_sync_updated=_optional_int(raw.get("last_sync_updated")),
            last_sync_unchanged=_optional_int(raw.get("last_sync_unchanged")),
            last_sync_failed=_optional_int(raw.get("last_sync_failed")),
            reauthorization_required=bool(raw.get("reauthorization_required")),
            folders=_parse_selected_items(raw.get("folders")),
            files=_parse_selected_items(raw.get("files")),
        )


class GoogleOAuthGateway(Protocol):
    """Token exchange and Drive identity at the Google boundary."""

    def exchange_code(self, code: str) -> GoogleOAuthGrant: ...

    def fetch_account_email(self, access_token: str) -> str | None: ...

    def revoke(self, token: str) -> None: ...


def authorization_url(settings: GoogleOAuthSettings, *, state: str) -> str:
    """Build Google's authorization URL. ``redirect_uri`` is used exactly."""
    if (
        settings.client_id is None
        or settings.client_secret is None
        or settings.redirect_uri is None
    ):
        raise GoogleOAuthError("OAuth client is not configured")
    query = urlencode(
        {
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "scope": _DRIVE_SCOPE,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{_AUTH_ENDPOINT}?{query}"


class HttpGoogleOAuthGateway:
    """Authorization-code exchange against Google's token endpoint."""

    def __init__(self, settings: GoogleOAuthSettings) -> None:
        self._settings = settings

    def exchange_code(self, code: str) -> GoogleOAuthGrant:
        """Trade an authorization code for tokens. Requires a refresh token."""
        settings = self._settings
        if (
            settings.client_id is None
            or settings.client_secret is None
            or settings.redirect_uri is None
        ):
            raise GoogleOAuthError("OAuth client is not configured")
        payload = _post_form(
            _TOKEN_ENDPOINT,
            {
                "code": code,
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "redirect_uri": settings.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        access = payload.get("access_token")
        refresh = payload.get("refresh_token")
        if not isinstance(access, str) or not access:
            raise GoogleOAuthError("token endpoint omitted access_token")
        if not isinstance(refresh, str) or not refresh:
            raise GoogleOAuthError("token endpoint omitted refresh_token")
        return GoogleOAuthGrant(access_token=access, refresh_token=refresh)

    def fetch_account_email(self, access_token: str) -> str | None:
        """Read the Drive account email with the existing readonly scope."""
        request = Request(
            _ABOUT_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            _LOG.info("Drive about lookup failed; account email omitted")
            return None
        user = payload.get("user") if isinstance(payload, dict) else None
        if not isinstance(user, dict):
            return None
        email = user.get("emailAddress")
        return email if isinstance(email, str) and email else None

    def revoke(self, token: str) -> None:
        """Best-effort revoke. Failure is logged without the token."""
        try:
            _post_form(_REVOKE_ENDPOINT, {"token": token})
        except GoogleOAuthError:
            _LOG.info("Google token revoke failed; local grant will still be cleared")


def build_oauth_drive_files(settings: GoogleOAuthSettings, *, refresh_token: str):
    """Build a Drive ``files`` resource from a stored refresh token."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if settings.client_id is None or settings.client_secret is None:
        raise GoogleOAuthError("OAuth client is not configured")
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=_TOKEN_ENDPOINT,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        scopes=(_DRIVE_SCOPE,),
    )
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return service.files()


def _post_form(url: str, fields: dict[str, str]) -> dict[str, object]:
    body = urlencode(fields).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as error:
        _LOG.info("Google OAuth HTTP error status=%s", error.code)
        raise GoogleOAuthError("Google OAuth request failed") from error
    except (URLError, TimeoutError) as error:
        _LOG.info("Google OAuth transport error")
        raise GoogleOAuthError("Google OAuth request failed") from error
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise GoogleOAuthError("Google OAuth response was not JSON") from error
    if not isinstance(payload, dict):
        raise GoogleOAuthError("Google OAuth response was not an object")
    return payload


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _connection_payload(connection: GoogleOAuthConnection) -> dict[str, object]:
    return {
        "refresh_token": connection.refresh_token,
        "access_token": connection.access_token,
        "account_email": connection.account_email,
        "folder_count": connection.folder_count,
        "folders": [{"id": item.id, "name": item.name} for item in connection.folders],
        "files": [{"id": item.id, "name": item.name} for item in connection.files],
        "last_synced_at": connection.last_synced_at,
        "last_sync_new": connection.last_sync_new,
        "last_sync_updated": connection.last_sync_updated,
        "last_sync_unchanged": connection.last_sync_unchanged,
        "last_sync_failed": connection.last_sync_failed,
        "reauthorization_required": connection.reauthorization_required,
    }


def _parse_selected_items(raw: object) -> tuple[GoogleDriveSelectedItem, ...]:
    if not isinstance(raw, list):
        return ()
    items: list[GoogleDriveSelectedItem] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("id")
        name = entry.get("name")
        if not isinstance(item_id, str) or not item_id.strip():
            continue
        if not isinstance(name, str) or not name.strip():
            continue
        if item_id in seen:
            continue
        seen.add(item_id)
        items.append(GoogleDriveSelectedItem(id=item_id, name=name))
    return tuple(items)


class ExclusiveLock:
    """Process-wide exclusive lock for one JSON grant/state path."""

    def __init__(self, path: Path) -> None:
        self._path = path.with_suffix(".lock.json")
        self._fd: int | None = None

    def __enter__(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(self._fd, fcntl.LOCK_EX)

    def __exit__(self, *_exc: object) -> None:
        fd = self._fd
        if fd is None:
            return
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        self._fd = None


def _atomic_write_json(path: Path, payload: object) -> None:
    """Write JSON to ``path`` at mode ``0600`` via temp file + ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix="google-oauth-tmp-",
        suffix=".json",
        dir=path.parent,
    )
    handle = None
    try:
        os.fchmod(fd, 0o600)
        handle = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except BaseException:
        if handle is not None:
            handle.close()
        elif fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _fsync_dir(directory: Path) -> None:
    try:
        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)
