"""Server-side Atlassian OAuth 2.0 (3LO) for the Jira connector.

Tokens stay on disk. This module never logs codes, tokens, or client secrets.

Requested scopes (least privilege): ``read:jira-work`` for project listing and
issue search, ``read:me`` for the connected account label, and
``offline_access`` for rotating refresh tokens.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import secrets
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from domain.errors import ConnectorAuthError
from infrastructure.config import JiraOAuthSettings
from infrastructure.connectors.jira.site import JiraSite

_LOG = logging.getLogger(__name__)

_AUTH_ENDPOINT = "https://auth.atlassian.com/authorize"
_TOKEN_ENDPOINT = "https://auth.atlassian.com/oauth/token"
_RESOURCES_ENDPOINT = "https://api.atlassian.com/oauth/token/accessible-resources"
_ME_ENDPOINT = "https://api.atlassian.com/me"
_JIRA_READ_SCOPE = "read:jira-work"
JIRA_OAUTH_SCOPE = "read:jira-work read:me offline_access"
_HTTP_TIMEOUT_SECONDS = 20.0
_REDACTED = "***"
_REJECTED_STATUSES = frozenset({400, 401, 403})


class JiraOAuthError(RuntimeError):
    """The Atlassian OAuth endpoint call failed or is not configured."""


class JiraOAuthInvalidGrantError(JiraOAuthError):
    """Atlassian rejected the code or refresh token; the user must reconnect."""


class JiraOAuthTransportError(JiraOAuthError):
    """Atlassian could not be reached or failed server-side; tokens unchanged."""


@dataclass(frozen=True, slots=True)
class JiraOAuthGrant:
    """Tokens from a code exchange or a rotating refresh."""

    access_token: str
    refresh_token: str | None
    expires_in: int | None = None

    def __repr__(self) -> str:
        return (
            f"JiraOAuthGrant(access_token={_REDACTED!r}, "
            f"refresh_token={_REDACTED!r}, expires_in={self.expires_in!r})"
        )


@dataclass(frozen=True, slots=True)
class AccessibleResource:
    """One container from ``GET /oauth/token/accessible-resources``.

    ``id`` is not unique across products; the product is inferred from
    ``scopes``.
    """

    id: str
    name: str
    url: str
    scopes: tuple[str, ...]


def eligible_jira_sites(resources: Sequence[AccessibleResource]) -> tuple[JiraSite, ...]:
    """Return distinct Jira sites the grant can read, sorted by name."""
    sites: dict[str, JiraSite] = {}
    for resource in resources:
        if _JIRA_READ_SCOPE not in resource.scopes or resource.id in sites:
            continue
        site_url = _canonical_site_url(resource.url)
        if site_url is None or not resource.id:
            continue
        sites[resource.id] = JiraSite(
            cloud_id=resource.id, site_url=site_url, name=resource.name or site_url
        )
    return tuple(
        sorted(sites.values(), key=lambda site: (site.name.casefold(), site.cloud_id))
    )


def _canonical_site_url(raw: str) -> str | None:
    parts = urlsplit(raw.strip())
    if parts.scheme.lower() != "https" or not parts.hostname:
        return None
    return f"https://{parts.hostname.lower()}"


class JiraOAuthGateway(Protocol):
    """Token exchange, rotating refresh, and identity at the Atlassian boundary."""

    def exchange_code(self, code: str) -> JiraOAuthGrant: ...

    def refresh(self, refresh_token: str) -> JiraOAuthGrant: ...

    def fetch_accessible_resources(
        self, access_token: str
    ) -> tuple[AccessibleResource, ...]: ...

    def fetch_account_name(self, access_token: str) -> str | None: ...


class HttpJiraOAuthGateway:
    """httpx implementation of :class:`JiraOAuthGateway`."""

    def __init__(
        self,
        settings: JiraOAuthSettings,
        *,
        timeout: float = _HTTP_TIMEOUT_SECONDS,
        transport: object | None = None,
    ) -> None:
        import httpx

        self._settings = settings
        self._httpx = httpx
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def exchange_code(self, code: str) -> JiraOAuthGrant:
        settings = self._settings
        if settings.redirect_uri is None:
            raise JiraOAuthError("OAuth client is not configured")
        payload = self._post_token(
            {
                "grant_type": "authorization_code",
                **self._client_credentials(),
                "code": code,
                "redirect_uri": settings.redirect_uri,
            }
        )
        return _grant_from_payload(payload)

    def refresh(self, refresh_token: str) -> JiraOAuthGrant:
        payload = self._post_token(
            {
                "grant_type": "refresh_token",
                **self._client_credentials(),
                "refresh_token": refresh_token,
            }
        )
        return _grant_from_payload(payload)

    def fetch_accessible_resources(
        self, access_token: str
    ) -> tuple[AccessibleResource, ...]:
        try:
            response = self._client.get(
                _RESOURCES_ENDPOINT, headers=_bearer_headers(access_token)
            )
        except self._httpx.HTTPError:
            _LOG.info("Atlassian accessible-resources transport error")
            raise JiraOAuthTransportError("Atlassian site lookup failed") from None
        if response.status_code in {401, 403}:
            raise ConnectorAuthError("Atlassian rejected the access token") from None
        if response.status_code >= 300:
            raise JiraOAuthTransportError("Atlassian site lookup failed") from None
        try:
            payload = response.json()
        except ValueError:
            raise JiraOAuthTransportError("Atlassian site lookup failed") from None
        if not isinstance(payload, list):
            raise JiraOAuthTransportError("Atlassian site lookup failed")
        return tuple(
            resource
            for resource in (_resource_from_payload(item) for item in payload)
            if resource is not None
        )

    def fetch_account_name(self, access_token: str) -> str | None:
        """Read the Atlassian account name for display only."""
        try:
            response = self._client.get(_ME_ENDPOINT, headers=_bearer_headers(access_token))
            response.raise_for_status()
            payload = response.json()
        except (self._httpx.HTTPError, ValueError):
            _LOG.info("Atlassian account lookup failed; account label omitted")
            return None
        name = payload.get("name") if isinstance(payload, Mapping) else None
        return name if isinstance(name, str) and name else None

    def _client_credentials(self) -> dict[str, str]:
        settings = self._settings
        if settings.client_id is None or settings.client_secret is None:
            raise JiraOAuthError("OAuth client is not configured")
        return {"client_id": settings.client_id, "client_secret": settings.client_secret}

    def _post_token(self, body: dict[str, str]) -> Mapping[str, object]:
        try:
            response = self._client.post(
                _TOKEN_ENDPOINT, json=body, headers={"Accept": "application/json"}
            )
        except self._httpx.HTTPError:
            _LOG.info("Atlassian OAuth transport error")
            raise JiraOAuthTransportError("Atlassian OAuth request failed") from None
        if response.status_code in _REJECTED_STATUSES:
            _LOG.info("Atlassian OAuth rejected status=%s", response.status_code)
            raise JiraOAuthInvalidGrantError("Atlassian rejected the OAuth grant") from None
        if response.status_code >= 300:
            _LOG.info("Atlassian OAuth HTTP error status=%s", response.status_code)
            raise JiraOAuthTransportError("Atlassian OAuth request failed") from None
        try:
            payload = response.json()
        except ValueError:
            raise JiraOAuthTransportError("Atlassian OAuth response was not JSON") from None
        if not isinstance(payload, Mapping):
            raise JiraOAuthTransportError("Atlassian OAuth response was not an object")
        return payload


def _bearer_headers(access_token: str) -> dict[str, str]:
    return {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}


def _resource_from_payload(raw: object) -> AccessibleResource | None:
    if not isinstance(raw, Mapping):
        return None
    rid, name, url, scopes = (raw.get(k) for k in ("id", "name", "url", "scopes"))
    if not isinstance(rid, str) or not isinstance(url, str):
        return None
    scope_list = scopes if isinstance(scopes, list) else []
    return AccessibleResource(
        id=rid,
        name=name if isinstance(name, str) else "",
        url=url,
        scopes=tuple(scope for scope in scope_list if isinstance(scope, str)),
    )


def _grant_from_payload(payload: Mapping[str, object]) -> JiraOAuthGrant:
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if not isinstance(access, str) or not access:
        raise JiraOAuthTransportError("token endpoint omitted access_token")
    return JiraOAuthGrant(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        expires_in=expires_in
        if isinstance(expires_in, int) and not isinstance(expires_in, bool)
        else None,
    )


def authorization_url(settings: JiraOAuthSettings, *, state: str) -> str:
    """Build Atlassian's 3LO authorization URL. ``redirect_uri`` is used exactly."""
    if (
        settings.client_id is None
        or settings.client_secret is None
        or settings.redirect_uri is None
    ):
        raise JiraOAuthError("OAuth client is not configured")
    query = urlencode(
        {
            "audience": "api.atlassian.com",
            "client_id": settings.client_id,
            "scope": JIRA_OAUTH_SCOPE,
            "redirect_uri": settings.redirect_uri,
            "state": state,
            "response_type": "code",
            "prompt": "consent",
        }
    )
    return f"{_AUTH_ENDPOINT}?{query}"


def new_jira_connector_id() -> str:
    """Return a new opaque connector instance id."""
    return uuid.uuid4().hex


@dataclass(frozen=True, slots=True)
class JiraOAuthConnection:
    """Persisted Atlassian grant plus the selected site and projects.

    Tokens are ``None`` after a rejected refresh so the consumed refresh token
    is never kept; the record remains so status and disconnect-purge still work.
    """

    access_token: str | None
    refresh_token: str | None
    access_token_expires_at: float | None = None
    account_name: str | None = None
    site: JiraSite | None = None
    project_keys: tuple[str, ...] = ()
    last_synced_at: str | None = None
    last_sync_new: int | None = None
    last_sync_updated: int | None = None
    last_sync_unchanged: int | None = None
    last_sync_removed: int | None = None
    last_sync_failed: int | None = None
    reauthorization_required: bool = False
    connector_id: str | None = None

    def __repr__(self) -> str:
        return (
            "JiraOAuthConnection("
            f"access_token={_REDACTED!r}, refresh_token={_REDACTED!r}, "
            f"account_name={self.account_name!r}, site={self.site!r}, "
            f"project_keys={self.project_keys!r}, "
            f"connector_id={self.connector_id!r}, "
            f"last_synced_at={self.last_synced_at!r}, "
            f"reauthorization_required={self.reauthorization_required})"
        )


class ConnectionStoreDelete:
    """Mutator result that unlinks the grant file."""


DELETE_GRANT = ConnectionStoreDelete()


class JiraOAuthStateStore:
    """Single-use CSRF ``state`` values with a TTL."""

    def __init__(self, path: Path, *, ttl_seconds: int) -> None:
        self._path = path
        self._ttl_seconds = ttl_seconds

    def issue(self) -> str:
        """Create and persist a new single-use state token."""
        token = secrets.token_urlsafe(32)
        with ExclusiveLock(self._path):
            now = time.time()
            items = {key: exp for key, exp in self._read().items() if exp > now}
            items[token] = now + self._ttl_seconds
            _atomic_write_json(self._path, items)
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
            _atomic_write_json(self._path, items)
            return expiry >= time.time()

    def _read(self) -> dict[str, float]:
        raw = _read_json(self._path)
        if not isinstance(raw, dict):
            return {}
        return {
            key: float(value)
            for key, value in raw.items()
            if isinstance(key, str)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }


class JiraOAuthConnectionStore:
    """JSON file store for the single-workspace Atlassian grant."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> JiraOAuthConnection | None:
        """Return the stored grant, or None when disconnected."""
        return _connection_from_payload(_read_json(self._path))

    def save(self, connection: JiraOAuthConnection) -> None:
        """Persist the grant. Overwrites the previous connection."""
        self.mutate(lambda _current: connection)

    def clear(self) -> None:
        """Delete the stored grant under the same lock as ``save``."""
        self.mutate(lambda _current: DELETE_GRANT)

    def mutate(
        self,
        mutator: Callable[
            [JiraOAuthConnection | None],
            JiraOAuthConnection | ConnectionStoreDelete | None,
        ],
    ) -> JiraOAuthConnection | None:
        """Re-read, apply ``mutator``, and persist atomically under the lock.

        Returning ``None`` from ``mutator`` keeps the current value.
        """
        with ExclusiveLock(self._path):
            current = _connection_from_payload(_read_json(self._path))
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


def _read_json(path: Path) -> object:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _connection_from_payload(raw: object) -> JiraOAuthConnection | None:
    if not isinstance(raw, dict):
        return None
    access = _optional_str(raw.get("access_token"))
    reauth = bool(raw.get("reauthorization_required"))
    if access is None and not reauth:
        return None
    keys = raw.get("project_keys")
    return JiraOAuthConnection(
        access_token=access,
        refresh_token=_optional_str(raw.get("refresh_token")),
        access_token_expires_at=_optional_float(raw.get("access_token_expires_at")),
        account_name=_optional_str(raw.get("account_name")),
        site=_site_from_payload(raw.get("site")),
        project_keys=tuple(k for k in keys if isinstance(k, str) and k)
        if isinstance(keys, list)
        else (),
        last_synced_at=_optional_str(raw.get("last_synced_at")),
        last_sync_new=_optional_int(raw.get("last_sync_new")),
        last_sync_updated=_optional_int(raw.get("last_sync_updated")),
        last_sync_unchanged=_optional_int(raw.get("last_sync_unchanged")),
        last_sync_removed=_optional_int(raw.get("last_sync_removed")),
        last_sync_failed=_optional_int(raw.get("last_sync_failed")),
        reauthorization_required=reauth,
        connector_id=_optional_str(raw.get("connector_id")),
    )


def _site_from_payload(raw: object) -> JiraSite | None:
    if not isinstance(raw, dict):
        return None
    cloud_id = _optional_str(raw.get("cloud_id"))
    site_url = _optional_str(raw.get("site_url"))
    if cloud_id is None or site_url is None:
        return None
    return JiraSite(
        cloud_id=cloud_id, site_url=site_url, name=_optional_str(raw.get("name")) or site_url
    )


def _connection_payload(connection: JiraOAuthConnection) -> dict[str, object]:
    site = connection.site
    return {
        "access_token": connection.access_token,
        "refresh_token": connection.refresh_token,
        "access_token_expires_at": connection.access_token_expires_at,
        "account_name": connection.account_name,
        "site": None
        if site is None
        else {"cloud_id": site.cloud_id, "site_url": site.site_url, "name": site.name},
        "project_keys": list(connection.project_keys),
        "last_synced_at": connection.last_synced_at,
        "last_sync_new": connection.last_sync_new,
        "last_sync_updated": connection.last_sync_updated,
        "last_sync_unchanged": connection.last_sync_unchanged,
        "last_sync_removed": connection.last_sync_removed,
        "last_sync_failed": connection.last_sync_failed,
        "reauthorization_required": connection.reauthorization_required,
        "connector_id": connection.connector_id,
    }


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


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
    fd, tmp = tempfile.mkstemp(prefix="jira-oauth-tmp-", suffix=".json", dir=path.parent)
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
