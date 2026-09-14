"""Server-side GitHub user OAuth for the GitHub connector.

Tokens stay on disk. This module never logs codes, tokens, or client secrets.

Requested OAuth scopes are ``repo`` for repository contents/issues and
``read:project``/``read:org`` for ProjectV2 reads. A fine-grained GitHub token
used outside OAuth should grant contents/issues read access and project reads.
"""

from __future__ import annotations

import base64
import fcntl
import json
import logging
import os
import secrets
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from infrastructure.config import GitHubOAuthSettings

_LOG = logging.getLogger(__name__)


def new_github_connector_id() -> str:
    """Return a new opaque connector instance id."""
    return uuid.uuid4().hex


def with_connector_id(
    connection: GitHubOAuthConnection,
    *,
    preferred: str | None = None,
) -> GitHubOAuthConnection:
    """Return ``connection`` with a stable connector_id, minting when missing."""
    if connection.connector_id:
        return connection
    connector_id = preferred.strip() if isinstance(preferred, str) else None
    if not connector_id:
        connector_id = new_github_connector_id()
    return replace(connection, connector_id=connector_id)


_AUTH_ENDPOINT = "https://github.com/login/oauth/authorize"
_TOKEN_ENDPOINT = "https://github.com/login/oauth/access_token"
_REVOKE_ENDPOINT = "https://api.github.com/applications/{client_id}/grant"
_USER_ENDPOINT = "https://api.github.com/user"
_GITHUB_SCOPE = "repo read:project read:org"
_GITHUB_HTTP_TIMEOUT_SECONDS = 20
_REDACTED = "***"


class GitHubOAuthError(RuntimeError):
    """The GitHub OAuth token endpoint, refresh, or revoke call failed."""


class ConnectionStoreDelete:
    """Mutator result that unlinks the grant file."""


DELETE_GRANT = ConnectionStoreDelete()


@dataclass(frozen=True, slots=True)
class GitHubOAuthGrant:
    """Tokens returned by a successful authorization-code exchange."""

    access_token: str
    refresh_token: str | None = None


@dataclass(frozen=True, slots=True)
class GitHubOAuthConnection:
    """Persisted GitHub grant plus presentation metadata (no secrets in repr)."""

    access_token: str
    refresh_token: str | None
    account_login: str | None
    owner: str | None
    repo: str | None
    project_owner: str | None
    project_number: int | None
    last_synced_at: str | None
    last_sync_new: int | None
    last_sync_updated: int | None
    last_sync_unchanged: int | None
    last_sync_removed: int | None
    last_sync_failed: int | None
    reauthorization_required: bool
    connector_id: str | None = None

    def __repr__(self) -> str:
        return (
            "GitHubOAuthConnection("
            f"access_token={_REDACTED!r}, refresh_token={_REDACTED!r}, "
            f"account_login={self.account_login!r}, owner={self.owner!r}, "
            f"repo={self.repo!r}, project_owner={self.project_owner!r}, "
            f"project_number={self.project_number!r}, "
            f"connector_id={self.connector_id!r}, "
            f"last_synced_at={self.last_synced_at!r}, "
            f"reauthorization_required={self.reauthorization_required})"
        )


class GitHubOAuthStateStore:
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


class GitHubOAuthConnectionStore:
    """JSON file store for the single-workspace user GitHub grant."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> GitHubOAuthConnection | None:
        """Return the stored grant, or None when disconnected."""
        return self._load_unlocked()

    def save(self, connection: GitHubOAuthConnection) -> None:
        """Persist the grant. Overwrites the previous connection."""
        self.mutate(lambda _current: connection)

    def clear(self) -> None:
        """Delete the stored grant under the same lock as ``save``."""
        self.mutate(lambda _current: DELETE_GRANT)

    def mutate(
        self,
        mutator: Callable[
            [GitHubOAuthConnection | None],
            GitHubOAuthConnection | ConnectionStoreDelete | None,
        ],
    ) -> GitHubOAuthConnection | None:
        """Re-read, apply ``mutator``, and persist under the exclusive lock."""
        with ExclusiveLock(self._path):
            current = self._load_unlocked()
            next_value = mutator(current)
            if next_value is None:
                return current
            if isinstance(next_value, ConnectionStoreDelete):
                try:
                    self._path.unlink()
                except FileNotFoundError:
                    pass
                return None
            _atomic_write_json(self._path, _connection_payload(next_value))
            return next_value

    def _load_unlocked(self) -> GitHubOAuthConnection | None:
        if not self._path.is_file():
            return None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        access = raw.get("access_token")
        if not isinstance(access, str) or not access:
            return None
        return GitHubOAuthConnection(
            access_token=access,
            refresh_token=_optional_str(raw.get("refresh_token")),
            account_login=_optional_str(raw.get("account_login")),
            owner=_optional_str(raw.get("owner")),
            repo=_optional_str(raw.get("repo")),
            project_owner=_optional_str(raw.get("project_owner")),
            project_number=_optional_int(raw.get("project_number")),
            last_synced_at=_optional_str(raw.get("last_synced_at")),
            last_sync_new=_optional_int(raw.get("last_sync_new")),
            last_sync_updated=_optional_int(raw.get("last_sync_updated")),
            last_sync_unchanged=_optional_int(raw.get("last_sync_unchanged")),
            last_sync_removed=_optional_int(raw.get("last_sync_removed")),
            last_sync_failed=_optional_int(raw.get("last_sync_failed")),
            reauthorization_required=bool(raw.get("reauthorization_required")),
            connector_id=_optional_str(raw.get("connector_id")),
        )


class GitHubOAuthGateway(Protocol):
    """Token exchange, refresh, revoke, and identity at the GitHub boundary."""

    def exchange_code(self, code: str) -> GitHubOAuthGrant: ...

    def refresh(self, refresh_token: str) -> GitHubOAuthGrant: ...

    def fetch_account_login(self, access_token: str) -> str | None: ...

    def revoke(self, token: str) -> None: ...


def authorization_url(settings: GitHubOAuthSettings, *, state: str) -> str:
    """Build GitHub's authorization URL. ``redirect_uri`` is used exactly."""
    if (
        settings.client_id is None
        or settings.client_secret is None
        or settings.redirect_uri is None
    ):
        raise GitHubOAuthError("OAuth client is not configured")
    query = urlencode(
        {
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "scope": _GITHUB_SCOPE,
            "state": state,
        }
    )
    return f"{_AUTH_ENDPOINT}?{query}"


class HttpGitHubOAuthGateway:
    """Authorization-code exchange against GitHub's token endpoint."""

    def __init__(self, settings: GitHubOAuthSettings) -> None:
        self._settings = settings

    def exchange_code(self, code: str) -> GitHubOAuthGrant:
        """Trade an authorization code for a GitHub access token."""
        settings = self._settings
        if (
            settings.client_id is None
            or settings.client_secret is None
            or settings.redirect_uri is None
        ):
            raise GitHubOAuthError("OAuth client is not configured")
        payload = _post_form(
            _TOKEN_ENDPOINT,
            {
                "code": code,
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "redirect_uri": settings.redirect_uri,
            },
        )
        return _grant_from_payload(payload)

    def refresh(self, refresh_token: str) -> GitHubOAuthGrant:
        """Refresh an expiring GitHub user token when GitHub supplied one."""
        settings = self._settings
        if settings.client_id is None or settings.client_secret is None:
            raise GitHubOAuthError("OAuth client is not configured")
        payload = _post_form(
            _TOKEN_ENDPOINT,
            {
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        return _grant_from_payload(payload)

    def fetch_account_login(self, access_token: str) -> str | None:
        """Read the GitHub account login for display only."""
        request = Request(
            _USER_ENDPOINT,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=_GITHUB_HTTP_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            _LOG.info("GitHub user lookup failed; account login omitted")
            return None
        login = payload.get("login") if isinstance(payload, dict) else None
        return login if isinstance(login, str) and login else None

    def revoke(self, token: str) -> None:
        """Best-effort revoke. Failure is logged without the token."""
        settings = self._settings
        if settings.client_id is None or settings.client_secret is None:
            return
        auth = base64.b64encode(
            f"{settings.client_id}:{settings.client_secret}".encode("utf-8")
        ).decode("ascii")
        body = json.dumps({"access_token": token}).encode("utf-8")
        request = Request(
            _REVOKE_ENDPOINT.format(client_id=settings.client_id),
            data=body,
            method="DELETE",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=_GITHUB_HTTP_TIMEOUT_SECONDS):
                pass
        except (HTTPError, URLError, TimeoutError):
            _LOG.info("GitHub token revoke failed; local grant will still be cleared")


def _grant_from_payload(payload: dict[str, object]) -> GitHubOAuthGrant:
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    if not isinstance(access, str) or not access:
        raise GitHubOAuthError("token endpoint omitted access_token")
    return GitHubOAuthGrant(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
    )


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
        with urlopen(request, timeout=_GITHUB_HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as error:
        _LOG.info("GitHub OAuth HTTP error status=%s", error.code)
        raise GitHubOAuthError("GitHub OAuth request failed") from error
    except (URLError, TimeoutError) as error:
        _LOG.info("GitHub OAuth transport error")
        raise GitHubOAuthError("GitHub OAuth request failed") from error
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise GitHubOAuthError("GitHub OAuth response was not JSON") from error
    if not isinstance(payload, dict):
        raise GitHubOAuthError("GitHub OAuth response was not an object")
    return payload


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _connection_payload(connection: GitHubOAuthConnection) -> dict[str, object]:
    return {
        "access_token": connection.access_token,
        "refresh_token": connection.refresh_token,
        "account_login": connection.account_login,
        "owner": connection.owner,
        "repo": connection.repo,
        "project_owner": connection.project_owner,
        "project_number": connection.project_number,
        "last_synced_at": connection.last_synced_at,
        "last_sync_new": connection.last_sync_new,
        "last_sync_updated": connection.last_sync_updated,
        "last_sync_unchanged": connection.last_sync_unchanged,
        "last_sync_removed": connection.last_sync_removed,
        "last_sync_failed": connection.last_sync_failed,
        "reauthorization_required": connection.reauthorization_required,
        "connector_id": connection.connector_id,
    }


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
        prefix="github-oauth-tmp-",
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
