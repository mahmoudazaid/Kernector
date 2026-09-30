"""Jira connector composition: Atlassian 3LO grant, site/project selection, sync.

One grant per workspace (#270 tracks multiple instances). Tokens never leave
the grant file; errors crossing this boundary carry fixed, provider-neutral text.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import NoReturn, TypeVar

from application.contracts import ConnectorSyncResponse
from application.errors import (
    ConfigurationError,
    InputRejectedError,
    JiraDataCenterModeError,
    JiraNotConnectedError,
    JiraReauthorizationRequiredError,
    JiraSelectionRequiredError,
    JiraSiteSelectionRequiredError,
)
from application.sync_connector import SyncConnectorDocuments
from composition import container as _container
from composition.errors import (
    ConnectorSyncError,
    DocumentOperationError,
    JiraConnectorError,
    JiraConnectorSyncError,
    JiraIssueLimitExceededError,
)
from domain.errors import ConnectorAuthError, ConnectorError, VectorStoreError
from domain.knowledge import CatalogStatus, SourceType
from domain.ports import DocumentCatalog, VectorStore
from infrastructure.catalog.errors import CatalogError
from infrastructure.config import Settings

logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_REQUEST_MESSAGE = "The Jira request failed."
_REAUTH_MESSAGE = "Jira authorization was revoked. Connect again."
_SYNC_MESSAGE = "The Jira connector sync failed."
_ISSUE_LIMIT_MESSAGE = "The selected Jira projects exceed the configured issue limit."
_REFRESH_SKEW_SECONDS = 60.0
_DATA_CENTER_MODE_MESSAGE = "Jira runs in Data Center mode; OAuth and site selection are unavailable."


@dataclass(frozen=True, slots=True)
class JiraSiteItem:
    """One Jira instance: a Cloud site (``cloud_id`` set) or a Data Center server."""

    instance_id: str
    name: str
    url: str
    cloud_id: str | None = None


@dataclass(frozen=True, slots=True)
class JiraSelection:
    """Saved sync targets: one site and its selected project keys."""

    site: JiraSiteItem | None
    project_keys: tuple[str, ...] = ()
    connector_id: str | None = None


def _data_center(settings: Settings) -> bool:
    return settings.jira_data_center is not None


def _reject_in_data_center(settings: Settings) -> None:
    if _data_center(settings):
        raise JiraDataCenterModeError(_DATA_CENTER_MODE_MESSAGE)


def _jira_oauth_ready(settings: Settings) -> bool:
    oauth = settings.jira_oauth
    return bool(oauth.client_id and oauth.client_secret and oauth.redirect_uri)


def _connection_store(settings: Settings):
    from infrastructure.connectors.jira.oauth import JiraOAuthConnectionStore

    return JiraOAuthConnectionStore(settings.jira_oauth.token_path)


def _state_store(settings: Settings):
    from infrastructure.connectors.jira.oauth import JiraOAuthStateStore

    return JiraOAuthStateStore(
        settings.jira_oauth.state_path,
        ttl_seconds=settings.jira_oauth.state_ttl_seconds,
    )


def _gateway(settings: Settings, gateway):
    if gateway is not None:
        return gateway
    from infrastructure.connectors.jira.oauth import HttpJiraOAuthGateway

    return HttpJiraOAuthGateway(settings.jira_oauth)


def _hub_redirect(settings: Settings, *, result: str) -> str:
    base = settings.jira_oauth.frontend_redirect
    if base is None:
        origin = (
            settings.http.cors_origins[0]
            if settings.http.cors_origins
            else "http://localhost:3000"
        )
        base = f"{origin.rstrip('/')}/documents"
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}jira={result}"


def _expires_at(expires_in: int | None) -> float | None:
    return None if expires_in is None else time.time() + expires_in


def start_jira_oauth(settings: Settings, *, state_store=None) -> str:
    """Issue CSRF state and return Atlassian's authorization URL."""
    _reject_in_data_center(settings)
    if not _jira_oauth_ready(settings):
        return _hub_redirect(settings, result="unconfigured")
    from infrastructure.connectors.jira.oauth import authorization_url

    store = state_store if state_store is not None else _state_store(settings)
    return authorization_url(settings.jira_oauth, state=store.issue())


def complete_jira_oauth(
    settings: Settings,
    *,
    state: str | None,
    code: str | None,
    error: str | None,
    state_store=None,
    connection_store=None,
    gateway=None,
) -> str:
    """Validate the callback, resolve Jira sites, persist the grant, return Hub URL.

    Exactly one eligible site is auto-selected; several require an explicit
    choice; none stores nothing. A reconnect keeps the connector id, and keeps
    the site and projects when the previous site is still accessible.
    """
    _reject_in_data_center(settings)
    if error == "access_denied":
        return _hub_redirect(settings, result="denied")
    states = state_store if state_store is not None else _state_store(settings)
    if not states.consume(state):
        return _hub_redirect(settings, result="invalid_state")
    if error or not code or not _jira_oauth_ready(settings):
        return _hub_redirect(settings, result="error")
    from domain.errors import ConnectorError
    from infrastructure.connectors.jira.oauth import (
        JiraOAuthConnection,
        JiraOAuthError,
        eligible_jira_sites,
        new_jira_connector_id,
    )

    oauth_gateway = _gateway(settings, gateway)
    tokens = connection_store if connection_store is not None else _connection_store(settings)
    try:
        grant = oauth_gateway.exchange_code(code)
        sites = eligible_jira_sites(
            oauth_gateway.fetch_accessible_resources(grant.access_token)
        )
    except (JiraOAuthError, ConnectorError):
        return _hub_redirect(settings, result="error")
    if not sites:
        return _hub_redirect(settings, result="no_site")
    account_name = oauth_gateway.fetch_account_name(grant.access_token)
    by_id = {site.cloud_id: site for site in sites}

    def _next(existing):
        previous_site = None if existing is None else existing.site
        kept_site = None if previous_site is None else by_id.get(previous_site.cloud_id)
        if kept_site is not None:
            site, project_keys = kept_site, existing.project_keys
        else:
            site = sites[0] if len(sites) == 1 else None
            project_keys = ()
        return JiraOAuthConnection(
            access_token=grant.access_token,
            refresh_token=grant.refresh_token,
            access_token_expires_at=_expires_at(grant.expires_in),
            account_name=account_name,
            site=site,
            project_keys=project_keys,
            connector_id=(
                existing.connector_id
                if existing is not None and existing.connector_id
                else new_jira_connector_id()
            ),
        )

    tokens.mutate(_next)
    return _hub_redirect(settings, result="connected")


def _require_grant(settings: Settings, connection_store):
    tokens = connection_store if connection_store is not None else _connection_store(settings)
    connection = tokens.load()
    if connection is None:
        raise JiraNotConnectedError("Jira is not connected")
    if connection.reauthorization_required or not connection.access_token:
        raise JiraReauthorizationRequiredError(_REAUTH_MESSAGE)
    return tokens, connection


def _without_tokens(current):
    return replace(
        current,
        access_token=None,
        refresh_token=None,
        access_token_expires_at=None,
        reauthorization_required=True,
    )


def _mark_reauth(tokens, error: BaseException | None = None) -> NoReturn:
    tokens.mutate(lambda current: None if current is None else _without_tokens(current))
    raise JiraReauthorizationRequiredError(_REAUTH_MESSAGE) from error


def _is_auth_failure(error: BaseException) -> bool:
    return isinstance(error, ConnectorAuthError) or isinstance(
        error.__cause__, ConnectorAuthError
    )


def _rotate(tokens, gateway, *, consumed: str | None) -> tuple[str, str | None]:
    """Refresh under the grant lock and persist both rotated tokens atomically.

    Atlassian refresh tokens are single-use: when another caller already
    rotated ``consumed``, the stored pair wins and no refresh is sent.
    """
    from infrastructure.connectors.jira.oauth import (
        JiraOAuthError,
        JiraOAuthInvalidGrantError,
    )

    outcome: dict[str, object] = {}

    def _apply(current):
        if current is None:
            outcome["error"] = JiraNotConnectedError("Jira is not connected")
            return None
        if current.reauthorization_required:
            outcome["error"] = JiraReauthorizationRequiredError(_REAUTH_MESSAGE)
            return None
        if current.refresh_token != consumed and current.access_token:
            outcome["pair"] = (current.access_token, current.refresh_token)
            return None
        if not current.refresh_token:
            outcome["error"] = JiraReauthorizationRequiredError(_REAUTH_MESSAGE)
            return _without_tokens(current)
        try:
            grant = gateway.refresh(current.refresh_token)
        except JiraOAuthInvalidGrantError:
            outcome["error"] = JiraReauthorizationRequiredError(_REAUTH_MESSAGE)
            return _without_tokens(current)
        except JiraOAuthError:
            outcome["error"] = JiraConnectorError(_REQUEST_MESSAGE)
            return None
        if not grant.refresh_token:
            outcome["error"] = JiraReauthorizationRequiredError(_REAUTH_MESSAGE)
            return _without_tokens(current)
        outcome["pair"] = (grant.access_token, grant.refresh_token)
        return replace(
            current,
            access_token=grant.access_token,
            refresh_token=grant.refresh_token,
            access_token_expires_at=_expires_at(grant.expires_in),
            reauthorization_required=False,
        )

    tokens.mutate(_apply)
    error = outcome.get("error")
    if isinstance(error, Exception):
        logger.info("Jira token refresh did not complete: %s", type(error).__name__)
        raise error
    pair = outcome["pair"]
    assert isinstance(pair, tuple)
    return pair


def _with_access_token(tokens, connection, gateway, operation: Callable[[str], _T]) -> _T:
    """Run ``operation`` with a fresh token; refresh once after an auth failure."""
    access, refresh = connection.access_token, connection.refresh_token
    expires_at = connection.access_token_expires_at
    if expires_at is not None and expires_at - _REFRESH_SKEW_SECONDS <= time.time():
        access, refresh = _rotate(tokens, gateway, consumed=refresh)
    try:
        return operation(access)
    except (ConnectorError, ConnectorSyncError) as error:
        if not _is_auth_failure(error):
            raise
    access, _refresh = _rotate(tokens, gateway, consumed=refresh)
    try:
        return operation(access)
    except (ConnectorError, ConnectorSyncError) as error:
        if _is_auth_failure(error):
            _mark_reauth(tokens, error)
        raise


def _fetch_sites(gateway, access_token: str):
    from infrastructure.connectors.jira.oauth import JiraOAuthError, eligible_jira_sites

    try:
        return eligible_jira_sites(gateway.fetch_accessible_resources(access_token))
    except JiraOAuthError as error:
        raise JiraConnectorError(_REQUEST_MESSAGE) from error


def _site_item(site) -> JiraSiteItem | None:
    if site is None:
        return None
    return JiraSiteItem(
        instance_id=site.instance_id,
        cloud_id=site.cloud_id,
        name=site.name,
        url=site.site_url,
    )


def list_jira_sites(
    settings: Settings, *, connection_store=None, gateway=None
) -> tuple[JiraSiteItem, ...]:
    """List Jira sites the stored grant can read, for the Hub site step."""
    _reject_in_data_center(settings)
    tokens, connection = _require_grant(settings, connection_store)
    oauth_gateway = _gateway(settings, gateway)
    sites = _with_access_token(
        tokens, connection, oauth_gateway, lambda token: _fetch_sites(oauth_gateway, token)
    )
    return tuple(item for item in map(_site_item, sites) if item is not None)


def put_jira_site(
    settings: Settings,
    *,
    cloud_id: str,
    connection_store=None,
    gateway=None,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
) -> JiraSelection:
    """Select one accessible site. Switching sites purges docs and clears projects."""
    _reject_in_data_center(settings)
    wanted = cloud_id.strip() if isinstance(cloud_id, str) else ""
    if not wanted:
        raise InputRejectedError("A Jira site is required.")
    tokens, connection = _require_grant(settings, connection_store)
    oauth_gateway = _gateway(settings, gateway)
    sites = _with_access_token(
        tokens, connection, oauth_gateway, lambda token: _fetch_sites(oauth_gateway, token)
    )
    site = next((candidate for candidate in sites if candidate.cloud_id == wanted), None)
    if site is None:
        raise InputRejectedError("The selected Jira site is not accessible.")
    previous = connection.site
    switched = previous is not None and previous.cloud_id != site.cloud_id

    def _apply(current):
        if current is None:
            raise JiraNotConnectedError("Jira is not connected")
        same = current.site is not None and current.site.cloud_id == site.cloud_id
        return replace(
            current, site=site, project_keys=current.project_keys if same else ()
        )

    saved = tokens.mutate(_apply)
    if switched:
        _purge_jira_docs(
            settings,
            connector_id=connection.connector_id,
            catalog=catalog,
            catalog_factory=catalog_factory,
            vector_store=vector_store,
            vector_store_factory=vector_store_factory,
        )
    return JiraSelection(
        site=_site_item(site),
        project_keys=() if saved is None else saved.project_keys,
        connector_id=connection.connector_id,
    )


@dataclass(frozen=True, slots=True)
class JiraProjectItem:
    """One Jira project row for the Hub picker."""

    key: str
    name: str


@dataclass(frozen=True, slots=True)
class JiraProjectPage:
    """One page of Jira projects; ``next_start_at`` is ``None`` on the last page."""

    items: tuple[JiraProjectItem, ...]
    next_start_at: int | None = None


_PROJECT_KEY = re.compile(r"[A-Z][A-Z0-9_]{0,254}")


def _client(client_factory, access_token: str, cloud_id: str):
    if client_factory is not None:
        return client_factory(access_token, cloud_id)
    from infrastructure.connectors.jira.client import HttpJiraClient

    return HttpJiraClient(access_token, cloud_id)


def _require_site(connection):
    if connection.site is None:
        raise JiraSiteSelectionRequiredError("Select a Jira site first.")
    return connection.site


def list_jira_projects(
    settings: Settings,
    *,
    start_at: int = 0,
    connection_store=None,
    gateway=None,
    client_factory=None,
) -> JiraProjectPage:
    """List projects on the selected site (Cloud) or the configured server (Data Center)."""
    if _data_center(settings):
        from composition.jira import data_center as jira_data_center

        return jira_data_center.list_projects(
            settings,
            start_at=start_at,
            state_store=connection_store,
            client_factory=client_factory,
        )
    if start_at < 0:
        raise InputRejectedError("start_at must be zero or greater.")
    tokens, connection = _require_grant(settings, connection_store)
    site = _require_site(connection)
    page_size = settings.jira.page_size

    def _list(token: str):
        return _client(client_factory, token, site.cloud_id).list_projects(
            start_at=start_at, max_results=page_size
        )

    try:
        page = _with_access_token(tokens, connection, _gateway(settings, gateway), _list)
    except ConnectorError as error:
        raise JiraConnectorError(_REQUEST_MESSAGE) from error
    return JiraProjectPage(
        items=tuple(JiraProjectItem(key=p.key, name=p.name) for p in page.items),
        next_start_at=None if page.is_last else page.next_start_at,
    )


def get_jira_selection(settings: Settings, *, connection_store=None) -> JiraSelection:
    """Return the saved site and project keys."""
    if _data_center(settings):
        from composition.jira import data_center as jira_data_center

        return jira_data_center.get_selection(settings, state_store=connection_store)
    _tokens, connection = _require_grant(settings, connection_store)
    return JiraSelection(
        site=_site_item(connection.site),
        project_keys=connection.project_keys,
        connector_id=connection.connector_id,
    )


def _normalize_project_keys(project_keys) -> tuple[str, ...]:
    keys: list[str] = []
    for raw in project_keys:
        key = raw.strip().upper() if isinstance(raw, str) else ""
        if not _PROJECT_KEY.fullmatch(key):
            raise InputRejectedError("Jira project keys must be valid project keys.")
        if key not in keys:
            keys.append(key)
    return tuple(keys)


def put_jira_selection(
    settings: Settings,
    *,
    project_keys,
    connection_store=None,
    gateway=None,
    client_factory=None,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
) -> JiraSelection:
    """Validate project access, save the selection, and purge deselected projects."""
    if _data_center(settings):
        from composition.jira import data_center as jira_data_center

        return jira_data_center.put_selection(
            settings,
            project_keys=project_keys,
            state_store=connection_store,
            client_factory=client_factory,
            catalog=catalog,
            catalog_factory=catalog_factory,
            vector_store=vector_store,
            vector_store_factory=vector_store_factory,
        )
    from infrastructure.connectors.jira.issue_documents import project_source_id_prefix

    keys = _normalize_project_keys(project_keys)
    tokens, connection = _require_grant(settings, connection_store)
    site = _require_site(connection)

    def _validate(token: str) -> tuple[str, ...]:
        client = _client(client_factory, token, site.cloud_id)
        return tuple(client.get_project(key).key for key in keys)

    if keys:
        try:
            keys = _with_access_token(
                tokens, connection, _gateway(settings, gateway), _validate
            )
        except ConnectorError as error:
            raise InputRejectedError(
                "A selected Jira project is inaccessible."
            ) from error

    def _apply(current):
        if current is None:
            raise JiraNotConnectedError("Jira is not connected")
        if current.reauthorization_required:
            raise JiraReauthorizationRequiredError(_REAUTH_MESSAGE)
        return replace(current, project_keys=keys)

    tokens.mutate(_apply)
    dropped = tuple(
        project_source_id_prefix(site.cloud_id, key)
        for key in connection.project_keys
        if key not in keys
    )
    if dropped:
        _purge_jira_docs(
            settings,
            connector_id=connection.connector_id,
            catalog=catalog,
            catalog_factory=catalog_factory,
            vector_store=vector_store,
            vector_store_factory=vector_store_factory,
            source_id_prefixes=dropped,
        )
    return JiraSelection(
        site=_site_item(site), project_keys=keys, connector_id=connection.connector_id
    )


@dataclass(frozen=True, slots=True)
class JiraLastSync:
    """Last Hub sync counts persisted with the grant."""

    synced_at: str
    new_count: int
    updated_count: int
    unchanged_count: int
    removed_count: int
    failed_count: int


@dataclass(frozen=True, slots=True)
class JiraStatus:
    """Atlassian grant, selected site/projects, and last sync for the Hub card."""

    available: bool
    oauth_ready: bool
    connected: bool = False
    account_name: str | None = None
    site: JiraSiteItem | None = None
    project_keys: tuple[str, ...] = ()
    document_count: int = 0
    last_sync: JiraLastSync | None = None
    reauthorization_required: bool = False
    setup_required: bool = False
    connection_state: str = "disconnected"
    sync_scope: str | None = None
    mode: str = "cloud"


def _last_sync(connection) -> JiraLastSync | None:
    counts = (
        connection.last_sync_new,
        connection.last_sync_updated,
        connection.last_sync_unchanged,
        connection.last_sync_removed,
        connection.last_sync_failed,
    )
    if connection.last_synced_at is None or any(count is None for count in counts):
        return None
    new, updated, unchanged, removed, failed = counts
    return JiraLastSync(
        synced_at=connection.last_synced_at,
        new_count=new,
        updated_count=updated,
        unchanged_count=unchanged,
        removed_count=removed,
        failed_count=failed,
    )


def _connection_state(connection) -> str:
    if connection is None:
        return "disconnected"
    if connection.reauthorization_required:
        return "reauthorization_required"
    if connection.site is None:
        return "site_selection_required"
    if not connection.project_keys:
        return "setup_required"
    return "ready"


def _document_count(
    settings: Settings,
    *,
    catalog: DocumentCatalog | None,
    catalog_factory: Callable[[], DocumentCatalog] | None,
) -> int:
    try:
        working = _container.resolve_catalog(
            settings, catalog=catalog, catalog_factory=catalog_factory
        )
        return working.count(source_type=SourceType.JIRA, status=CatalogStatus.READY)
    except (
        CatalogError,
        ConfigurationError,
        DocumentOperationError,
        OSError,
        ValueError,
    ):
        logger.warning("Jira document count unavailable", exc_info=True)
        return 0


def jira_status(
    settings: Settings,
    *,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
) -> JiraStatus:
    """Report the Jira connection without calling Atlassian or the Data Center server."""
    if settings.jira_data_center is not None:
        from composition.jira import data_center as jira_data_center

        return jira_data_center.status(
            settings, catalog=catalog, catalog_factory=catalog_factory
        )
    connection = _connection_store(settings).load()
    available = importlib.util.find_spec("httpx") is not None
    oauth_ready = _jira_oauth_ready(settings)
    if connection is None:
        return JiraStatus(available=available, oauth_ready=oauth_ready)
    state = _connection_state(connection)
    site = _site_item(connection.site)
    scope = None
    if site is not None and connection.project_keys:
        scope = f"{site.name} · {', '.join(connection.project_keys)}"
    return JiraStatus(
        available=available,
        oauth_ready=oauth_ready,
        connected=True,
        account_name=connection.account_name,
        site=site,
        project_keys=connection.project_keys,
        document_count=_document_count(
            settings, catalog=catalog, catalog_factory=catalog_factory
        ),
        last_sync=_last_sync(connection),
        reauthorization_required=connection.reauthorization_required,
        setup_required=state in {"site_selection_required", "setup_required"},
        connection_state=state,
        sync_scope=scope,
    )


def _ensure_connector_id(tokens, connection):
    if connection.connector_id:
        return connection
    from infrastructure.connectors.jira.oauth import new_jira_connector_id

    new_id = new_jira_connector_id()
    saved = tokens.mutate(
        lambda current: None
        if current is None or current.connector_id
        else replace(current, connector_id=new_id)
    )
    if saved is None:
        raise JiraNotConnectedError("Jira is not connected")
    return saved


def sync_jira_oauth(
    settings: Settings,
    *,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
    connection_store=None,
    gateway=None,
    client_factory=None,
) -> ConnectorSyncResponse:
    """Sync the selected Jira projects into the knowledge base.

    The site must still be accessible to the grant. Listing is complete before
    any write, so issue-limit and pagination failures leave the catalog unchanged.
    """
    if _data_center(settings):
        from composition.jira import data_center as jira_data_center

        return jira_data_center.sync(
            settings,
            catalog=catalog,
            catalog_factory=catalog_factory,
            vector_store=vector_store,
            vector_store_factory=vector_store_factory,
            state_store=connection_store,
            client_factory=client_factory,
        )
    from datetime import datetime, timezone

    from infrastructure.connectors.jira.connector import JiraKnowledgeConnector
    from infrastructure.connectors.jira.errors import (
        JiraIssueLimitExceededError as _InfraIssueLimitExceededError,
    )
    from infrastructure.connectors.jira.issue_documents import JiraIssueConfig

    tokens, connection = _require_grant(settings, connection_store)
    site = _require_site(connection)
    if not connection.project_keys:
        raise JiraSelectionRequiredError("Select Jira projects before syncing.")
    connection = _ensure_connector_id(tokens, connection)
    connector_id = connection.connector_id
    oauth_gateway = _gateway(settings, gateway)
    working = _container.resolve_catalog(
        settings, catalog=catalog, catalog_factory=catalog_factory
    )
    get_store = _container.lazy_vector_store(
        settings, vector_store=vector_store, vector_store_factory=vector_store_factory
    )
    config = JiraIssueConfig(
        site=site,
        project_keys=connection.project_keys,
        connector_id=connector_id,
        include_comments=settings.jira.include_comments,
        page_size=settings.jira.page_size,
        max_issues=settings.jira.max_issues,
    )

    def _run(token: str) -> ConnectorSyncResponse:
        accessible = {candidate.cloud_id for candidate in _fetch_sites(oauth_gateway, token)}
        if site.cloud_id not in accessible:
            _mark_reauth(tokens)
        connector = JiraKnowledgeConnector(
            _client(client_factory, token, site.cloud_id), config
        )
        try:
            return SyncConnectorDocuments(
                connector=connector,
                catalog=working,
                ingest_factory=lambda: _container.build_ingest_knowledge(
                    settings, vector_store=get_store()
                ),
                reconcile_missing=True,
                reconcile_source_types=frozenset({SourceType.JIRA}),
                reconcile_source_id_prefixes=frozenset({f"{site.cloud_id}/"}),
                reconcile_connector_ids=frozenset({connector_id}),
                vector_store_factory=get_store,
            ).execute()
        except _InfraIssueLimitExceededError as error:
            raise JiraIssueLimitExceededError(_ISSUE_LIMIT_MESSAGE) from error
        except (ConnectorError, CatalogError, VectorStoreError) as error:
            raise JiraConnectorSyncError(_SYNC_MESSAGE) from error

    try:
        result = _with_access_token(tokens, connection, oauth_gateway, _run)
    except ConnectorError as error:
        raise JiraConnectorSyncError(_SYNC_MESSAGE) from error
    except JiraConnectorError as error:
        raise JiraConnectorSyncError(_SYNC_MESSAGE) from error
    synced_at = datetime.now(timezone.utc).isoformat()
    tokens.mutate(
        lambda current: None
        if current is None
        else replace(
            current,
            last_synced_at=synced_at,
            last_sync_new=result.ingested_count,
            last_sync_updated=result.updated_count,
            last_sync_unchanged=result.skipped_count,
            last_sync_removed=result.removed_count,
            last_sync_failed=result.failed_count,
        )
    )
    return result


def disconnect_jira_oauth(
    settings: Settings,
    *,
    connection_store=None,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
) -> None:
    """Delete the local grant and purge this connector's Jira documents.

    Atlassian has no public 3LO revoke endpoint; the user can remove app
    access from their Atlassian account settings.
    """
    if _data_center(settings):
        from composition.jira import data_center as jira_data_center

        jira_data_center.disconnect(
            settings,
            state_store=connection_store,
            catalog=catalog,
            catalog_factory=catalog_factory,
            vector_store=vector_store,
            vector_store_factory=vector_store_factory,
        )
        return
    tokens = connection_store if connection_store is not None else _connection_store(settings)
    connection = tokens.load()
    if connection is None:
        raise JiraNotConnectedError("Jira is not connected")
    tokens.clear()
    _purge_jira_docs(
        settings,
        connector_id=connection.connector_id,
        catalog=catalog,
        catalog_factory=catalog_factory,
        vector_store=vector_store,
        vector_store_factory=vector_store_factory,
    )


def _purge_jira_docs(
    settings: Settings,
    *,
    connector_id: str | None,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
    source_id_prefixes: tuple[str, ...] | None = None,
) -> None:
    """Delete Jira catalog+vector rows owned by ``connector_id``.

    ``source_id_prefixes`` narrows the purge (deselected projects); ``None``
    removes every Jira row for the connector (disconnect, site switch).
    """
    if not connector_id:
        return
    working = _container.resolve_catalog(
        settings, catalog=catalog, catalog_factory=catalog_factory
    )
    targets = [
        row
        for row in working.all()
        if row.reference.source_type == SourceType.JIRA
        and row.connector_id == connector_id
        and (
            source_id_prefixes is None
            or row.reference.source_id.startswith(source_id_prefixes)
        )
    ]
    if not targets:
        return
    store = _container.lazy_vector_store(
        settings, vector_store=vector_store, vector_store_factory=vector_store_factory
    )()
    try:
        for row in targets:
            store.delete_source(row.reference)
            working.delete(row.reference)
    except (CatalogError, VectorStoreError) as error:
        raise DocumentOperationError(str(error)) from error
