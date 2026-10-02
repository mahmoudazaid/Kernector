"""Jira Data Center / Server composition: PAT-authenticated project selection and sync.

The Personal Access Token lives only in settings; it is never persisted, logged,
or returned. Errors crossing this boundary carry fixed, provider-neutral text.
"""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Callable
from dataclasses import replace
from typing import TypeVar

from application.contracts import ConnectorSyncResponse
from application.errors import (
    ConfigurationError,
    InputRejectedError,
    JiraDataCenterCredentialsRejectedError,
    JiraSelectionRequiredError,
    JiraSetupRequiredError,
)
from application.sync_connector import SyncConnectorDocuments
from composition import container as _container
from composition.errors import (
    DocumentOperationError,
    JiraConnectorError,
    JiraConnectorSyncError,
    JiraIssueLimitExceededError,
)
from composition.jira.cloud import (
    JiraProjectItem,
    JiraProjectPage,
    JiraSelection,
    JiraSiteItem,
    JiraStatus,
    _is_auth_failure,
    _last_sync,
    _normalize_project_keys,
    _purge_jira_docs,
)
from domain.errors import ConnectorError, ConnectorNotFoundError, VectorStoreError
from domain.knowledge import CatalogStatus, SourceType
from domain.ports import DocumentCatalog, VectorStore
from infrastructure.catalog.errors import CatalogError
from infrastructure.config import Settings

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

_REQUEST_MESSAGE = "The Jira request failed."
_SETUP_MESSAGE = "Set JIRA_DC_BASE_URL and JIRA_DC_TOKEN to a reachable Jira Data Center."
_NOT_JIRA_MESSAGE = "The configured Jira Data Center URL is not a Jira REST API."
_REJECTED_MESSAGE = "Jira Data Center rejected the configured token. Update JIRA_DC_TOKEN."
_SYNC_MESSAGE = "The Jira connector sync failed."
_ISSUE_LIMIT_MESSAGE = "The selected Jira projects exceed the configured issue limit."


def _configured(settings: Settings) -> bool:
    dc = settings.jira_data_center
    return dc is not None and dc.configured


def _store(settings: Settings, state_store=None):
    if state_store is not None:
        return state_store
    from infrastructure.connectors.jira.data_center_state import JiraDataCenterStateStore

    assert settings.jira_data_center is not None
    return JiraDataCenterStateStore(settings.jira_data_center.state_path)


def _connector_document_count(
    settings: Settings,
    connector_id: str | None,
    *,
    catalog: DocumentCatalog | None,
    catalog_factory,
) -> int:
    if not connector_id:
        return 0
    try:
        working = _container.resolve_catalog(
            settings, catalog=catalog, catalog_factory=catalog_factory
        )
        return sum(
            1
            for row in working.all()
            if row.reference.source_type == SourceType.JIRA
            and row.connector_id == connector_id
            and row.status == CatalogStatus.READY
        )
    except (CatalogError, ConfigurationError, DocumentOperationError, OSError, ValueError):
        logger.warning("Jira document count unavailable", exc_info=True)
        return 0


def status(
    settings: Settings,
    *,
    catalog: DocumentCatalog | None = None,
    catalog_factory=None,
    state_store=None,
) -> JiraStatus:
    """Report Data Center configuration and saved state without network calls."""
    available = importlib.util.find_spec("httpx") is not None
    if not _configured(settings):
        return JiraStatus(
            available=available,
            oauth_ready=False,
            setup_required=True,
            connection_state="setup_required",
            mode="data_center",
        )
    state = _store(settings, state_store).load()
    site = None if state is None else _dc_site_item(state.site)
    keys = () if state is None else state.project_keys
    rejected = state is not None and state.credentials_rejected
    if rejected:
        connection_state = "reauthorization_required"
    elif not keys:
        connection_state = "setup_required"
    else:
        connection_state = "ready"
    scope = f"{site.name} · {', '.join(keys)}" if site is not None and keys else None
    return JiraStatus(
        available=available,
        oauth_ready=False,
        connected=True,
        site=site,
        project_keys=keys,
        document_count=_connector_document_count(
            settings,
            None if state is None else state.connector_id,
            catalog=catalog,
            catalog_factory=catalog_factory,
        ),
        last_sync=None if state is None else _last_sync(state),
        reauthorization_required=rejected,
        setup_required=connection_state != "ready",
        connection_state=connection_state,
        sync_scope=scope,
        mode="data_center",
    )


def _dc_site_item(site) -> JiraSiteItem | None:
    if site is None:
        return None
    return JiraSiteItem(instance_id=site.instance_id, name=site.name, url=site.site_url)


def _require_configured(settings: Settings) -> None:
    if not _configured(settings):
        raise JiraSetupRequiredError(_SETUP_MESSAGE)


def _client(settings: Settings, client_factory):
    dc = settings.jira_data_center
    assert dc is not None and dc.base_url is not None and dc.token is not None
    if client_factory is not None:
        return client_factory(dc.base_url, dc.token)
    from infrastructure.connectors.jira import data_center

    return data_center.HttpJiraDataCenterClient(dc.base_url, dc.token)


def authenticated_call(store, operation: Callable[[], _T]) -> _T:
    """Run ``operation``; record a rejected token, and clear it after any success."""
    from infrastructure.connectors.jira.data_center_state import JiraDataCenterState

    try:
        result = operation()
    except ConnectorError as error:
        if not _is_auth_failure(error):
            raise
        store.mutate(
            lambda current: replace(
                current or JiraDataCenterState(), credentials_rejected=True
            )
        )
        raise JiraDataCenterCredentialsRejectedError(_REJECTED_MESSAGE) from error
    store.mutate(
        lambda current: replace(current, credentials_rejected=False)
        if current is not None and current.credentials_rejected
        else None
    )
    return result


def list_projects(
    settings: Settings,
    *,
    start_at: int = 0,
    state_store=None,
    client_factory=None,
) -> JiraProjectPage:
    """List projects visible to the configured token; no site step in Data Center."""
    if start_at < 0:
        raise InputRejectedError("start_at must be zero or greater.")
    _require_configured(settings)
    client = _client(settings, client_factory)
    try:
        page = authenticated_call(
            _store(settings, state_store),
            lambda: client.list_projects(
                start_at=start_at, max_results=settings.jira.page_size
            ),
        )
    except ConnectorNotFoundError as error:
        raise JiraSetupRequiredError(_NOT_JIRA_MESSAGE) from error
    except ConnectorError as error:
        raise JiraConnectorError(_REQUEST_MESSAGE) from error
    return JiraProjectPage(
        items=tuple(JiraProjectItem(key=p.key, name=p.name) for p in page.items),
        next_start_at=None if page.is_last else page.next_start_at,
    )


def get_selection(settings: Settings, *, state_store=None) -> JiraSelection:
    """Return the saved instance and project keys without network calls."""
    _require_configured(settings)
    state = _store(settings, state_store).load()
    if state is None:
        return JiraSelection(site=None)
    return JiraSelection(
        site=_dc_site_item(state.site),
        project_keys=state.project_keys,
        connector_id=state.connector_id,
    )


def _server_info(client):
    """Resolve the instance identity; auth failures pass through for ``authenticated_call``."""
    try:
        return client.server_info()
    except ConnectorNotFoundError as error:
        raise JiraSetupRequiredError(_NOT_JIRA_MESSAGE) from error
    except ConnectorError as error:
        if _is_auth_failure(error):
            raise
        raise JiraConnectorError(_REQUEST_MESSAGE) from error


def put_selection(
    settings: Settings,
    *,
    project_keys,
    state_store=None,
    client_factory=None,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
) -> JiraSelection:
    """Validate project access, save the selection, and purge dropped documents.

    A changed server identity purges every document of this connector first.
    """
    from infrastructure.connectors.jira.data_center_state import JiraDataCenterState
    from infrastructure.connectors.jira.issue_documents import project_source_id_prefix
    from infrastructure.connectors.jira.oauth import new_jira_connector_id

    keys = _normalize_project_keys(project_keys)
    _require_configured(settings)
    store = _store(settings, state_store)
    previous = store.load() or JiraDataCenterState()
    site = previous.site
    if keys:
        client = _client(settings, client_factory)

        def _validate():
            resolved = _server_info(client)
            try:
                return resolved, tuple(client.get_project(key).key for key in keys)
            except ConnectorError as error:
                if _is_auth_failure(error):
                    raise
                raise InputRejectedError(
                    "A selected Jira project is inaccessible."
                ) from error

        site, keys = authenticated_call(store, _validate)
    switched = (
        previous.site is not None
        and site is not None
        and previous.site.instance_id != site.instance_id
    )

    def _apply(current):
        base = current or JiraDataCenterState()
        return replace(
            base,
            connector_id=base.connector_id or new_jira_connector_id(),
            site=site,
            project_keys=keys,
        )

    saved = store.mutate(_apply)
    assert saved is not None

    def _purge(source_id_prefixes: tuple[str, ...] | None = None) -> None:
        _purge_jira_docs(
            settings,
            connector_id=previous.connector_id,
            catalog=catalog,
            catalog_factory=catalog_factory,
            vector_store=vector_store,
            vector_store_factory=vector_store_factory,
            source_id_prefixes=source_id_prefixes,
        )

    if switched:
        _purge()
    elif previous.site is not None:
        dropped = tuple(
            project_source_id_prefix(previous.site.instance_id, key)
            for key in previous.project_keys
            if key not in keys
        )
        if dropped:
            _purge(dropped)
    return JiraSelection(
        site=_dc_site_item(saved.site),
        project_keys=saved.project_keys,
        connector_id=saved.connector_id,
    )


def sync(
    settings: Settings,
    *,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
    state_store=None,
    client_factory=None,
) -> ConnectorSyncResponse:
    """Sync the selected projects; listing completes before any write.

    A changed server identity purges this connector's documents and clears the
    selection instead of syncing into a different instance.
    """
    from datetime import datetime, timezone

    from infrastructure.connectors.jira.connector import JiraKnowledgeConnector
    from infrastructure.connectors.jira.data_center_state import JiraDataCenterState
    from infrastructure.connectors.jira.errors import (
        JiraIssueLimitExceededError as _InfraIssueLimitExceededError,
    )
    from infrastructure.connectors.jira.issue_documents import JiraIssueConfig
    from infrastructure.connectors.jira.oauth import new_jira_connector_id
    from infrastructure.connectors.jira.wiki import wiki_to_markdown

    _require_configured(settings)
    store = _store(settings, state_store)
    state = store.load()
    if state is None or not state.project_keys:
        raise JiraSelectionRequiredError("Select Jira projects before syncing.")
    client = _client(settings, client_factory)
    try:
        site = authenticated_call(store, lambda: _server_info(client))
    except JiraConnectorError as error:
        raise JiraConnectorSyncError(_SYNC_MESSAGE) from error
    if state.site is None or state.site.instance_id != site.instance_id:
        store.mutate(
            lambda current: replace(
                current or JiraDataCenterState(), site=site, project_keys=()
            )
        )
        _purge_jira_docs(
            settings,
            connector_id=state.connector_id,
            catalog=catalog,
            catalog_factory=catalog_factory,
            vector_store=vector_store,
            vector_store_factory=vector_store_factory,
        )
        raise JiraSelectionRequiredError(
            "The Jira Data Center instance changed. Select projects again."
        )
    saved = store.mutate(
        lambda current: None
        if current is None or current.connector_id
        else replace(current, connector_id=new_jira_connector_id())
    )
    connector_id = (saved or state).connector_id
    assert connector_id is not None
    working = _container.resolve_catalog(
        settings, catalog=catalog, catalog_factory=catalog_factory
    )
    get_store = _container.lazy_vector_store(
        settings, vector_store=vector_store, vector_store_factory=vector_store_factory
    )
    config = JiraIssueConfig(
        site=site,
        project_keys=state.project_keys,
        connector_id=connector_id,
        include_comments=settings.jira.include_comments,
        page_size=settings.jira.page_size,
        max_issues=settings.jira.max_issues,
        render_text=wiki_to_markdown,
        deployment="data_center",
    )
    sync_documents = SyncConnectorDocuments(
        connector=JiraKnowledgeConnector(client, config),
        catalog=working,
        ingest_factory=lambda: _container.build_ingest_knowledge(
            settings, vector_store=get_store()
        ),
        reconcile_missing=True,
        reconcile_source_types=frozenset({SourceType.JIRA}),
        reconcile_source_id_prefixes=frozenset({f"{site.instance_id}/"}),
        reconcile_connector_ids=frozenset({connector_id}),
        vector_store_factory=get_store,
    )
    try:
        result = authenticated_call(store, sync_documents.execute)
    except _InfraIssueLimitExceededError as error:
        raise JiraIssueLimitExceededError(_ISSUE_LIMIT_MESSAGE) from error
    except (ConnectorError, CatalogError, VectorStoreError) as error:
        raise JiraConnectorSyncError(_SYNC_MESSAGE) from error
    synced_at = datetime.now(timezone.utc).isoformat()
    store.mutate(
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


def disconnect(
    settings: Settings,
    *,
    state_store=None,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
) -> None:
    """Delete saved state and this connector's documents; the env token is untouched."""
    store = _store(settings, state_store)
    state = store.load()
    if state is None:
        return
    store.clear()
    _purge_jira_docs(
        settings,
        connector_id=state.connector_id,
        catalog=catalog,
        catalog_factory=catalog_factory,
        vector_store=vector_store,
        vector_store_factory=vector_store_factory,
    )
