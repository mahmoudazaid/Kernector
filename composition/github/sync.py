"""GitHub connector construction and knowledge-base sync."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from application.contracts import ConnectorSyncOutcome, ConnectorSyncResponse
from application.errors import (
    ConfigurationError,
    GitHubSelectionRequiredError,
)
from application.sync_connector import SyncConnectorDocuments
from composition import container as _container
from composition.errors import (
    ConnectorSyncError,
    GitHubConnectorSyncError,
)
from composition.github.connection import (
    GITHUB_CLIENT_MISSING_MESSAGE,
    coalesce_text,
    mark_github_reauth,
    require_github_grant,
)
from composition.github.models import GitHubRepoTarget
from composition.github.targets import (
    repositories_from_connection,
    resolve_target_file_rules,
)
from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    VectorStoreError,
)
from domain.knowledge import SourceType
from domain.ports import (
    DocumentCatalog,
    KnowledgeConnector,
    VectorStore,
)
from infrastructure.catalog.errors import CatalogError
from infrastructure.config import Settings


_GITHUB_CONFIG_MESSAGE = "GitHub connector configuration is invalid."
_GITHUB_SYNC_MESSAGE = "The GitHub connector sync failed."


def _github_reconcile_connector_ids(github) -> frozenset[str]:
    connector_id = getattr(github, "connector_id", None)
    if isinstance(connector_id, str) and connector_id.strip():
        return frozenset({connector_id.strip()})
    return frozenset()


def build_github_connector(settings: Settings) -> KnowledgeConnector:
    """Build the GitHub connector from runtime settings."""
    try:
        from infrastructure.connectors.github.connector import (
            GitHubConnectorConfigError,
            GitHubKnowledgeConnector,
        )
    except ImportError as error:
        raise ConfigurationError(GITHUB_CLIENT_MISSING_MESSAGE) from error
    try:
        return GitHubKnowledgeConnector(settings.github)
    except GitHubConnectorConfigError as error:
        raise ConfigurationError(_GITHUB_CONFIG_MESSAGE) from error


def sync_github(
    settings: Settings,
    *,
    connector: KnowledgeConnector | None = None,
    catalog: DocumentCatalog | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
    reconcile_source_id_prefixes: frozenset[str] | None = None,
) -> ConnectorSyncResponse:
    """Synchronize configured GitHub content into the knowledge base."""
    try:
        if connector is None:
            connector = build_github_connector(settings)
        if catalog is None:
            catalog = _container.build_document_catalog(settings)
        get_store = _container.lazy_vector_store(
            settings,
            vector_store=vector_store,
            vector_store_factory=vector_store_factory,
        )
        connector_ids = _github_reconcile_connector_ids(settings.github)
        if not connector_ids:
            raise ConfigurationError(
                "GitHub connector_id is required before synchronizing."
            )

        return SyncConnectorDocuments(
            connector=connector,
            catalog=catalog,
            ingest_factory=lambda: _container.build_ingest_knowledge(
                settings,
                vector_store=get_store(),
            ),
            processing_profile=_container.build_processing_profile(settings),
            reconcile_missing=True,
            reconcile_source_types=frozenset({SourceType.GITHUB}),
            reconcile_connector_ids=connector_ids,
            reconcile_source_id_prefixes=reconcile_source_id_prefixes,
            vector_store_factory=get_store,
        ).execute()
    except ConnectorError as error:
        raise GitHubConnectorSyncError(_GITHUB_SYNC_MESSAGE) from error
    except CatalogError as error:
        raise GitHubConnectorSyncError(_GITHUB_SYNC_MESSAGE) from error
    except VectorStoreError as error:
        raise GitHubConnectorSyncError(_GITHUB_SYNC_MESSAGE) from error


def build_github_oauth_connector(settings: Settings, *, token: str) -> KnowledgeConnector:
    """Build a GitHub connector from a stored OAuth access token."""
    github = replace(settings.github, token=token)
    try:
        from infrastructure.connectors.github.connector import (
            GitHubConnectorConfigError,
            GitHubKnowledgeConnector,
        )
    except ImportError as error:
        raise ConfigurationError(GITHUB_CLIENT_MISSING_MESSAGE) from error
    try:
        return GitHubKnowledgeConnector(github)
    except GitHubConnectorConfigError as error:
        raise ConfigurationError(_GITHUB_CONFIG_MESSAGE) from error


def sync_github_oauth(
    settings: Settings,
    *,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
    connection_store=None,
    oauth_gateway=None,
) -> ConnectorSyncResponse:
    """Synchronize GitHub using the stored user OAuth grant."""
    from datetime import datetime, timezone

    from infrastructure.connectors.github.oauth import (
        GitHubOAuthError,
        HttpGitHubOAuthGateway,
        with_connector_id,
    )

    tokens_store, connection = require_github_grant(
        settings, connection_store=connection_store
    )
    if not connection.connector_id:
        tokens_store.mutate(
            lambda current: None
            if current is None
            else with_connector_id(
                current, preferred=settings.github.connector_id
            )
        )
        connection = tokens_store.load()
        assert connection is not None
    gateway = (
        oauth_gateway
        if oauth_gateway is not None
        else HttpGitHubOAuthGateway(settings.github_oauth)
    )
    access_token = connection.access_token
    grant_repositories = repositories_from_connection(
        owner=connection.owner,
        repo=connection.repo,
        repositories=connection.repositories,
    )
    # Hub selection on the grant: multi-target sync. Empty grant falls back to
    # legacy settings.github owner/repo/project as a single combined connector.
    use_grant_selection = bool(
        grant_repositories
        or (
            connection.project_owner
            and connection.project_number is not None
        )
    )
    if use_grant_selection:
        repositories = grant_repositories
        project_owner = connection.project_owner
        project_number = connection.project_number
    else:
        owner = coalesce_text(connection.owner, settings.github.owner)
        repo = coalesce_text(connection.repo, settings.github.repo)
        repositories = (
            (GitHubRepoTarget(owner=owner, repo=repo),)
            if owner and repo
            else ()
        )
        project_owner = coalesce_text(
            connection.project_owner, settings.github.project_owner
        )
        project_number = (
            connection.project_number
            if connection.project_number is not None
            else settings.github.project_number
        )
    has_scope = bool(
        repositories or (project_owner and project_number is not None)
    )
    if not has_scope:
        raise GitHubSelectionRequiredError(
            "Select a GitHub repository or project before syncing."
        )
    owner = repositories[0].owner if repositories else None
    repo = repositories[0].repo if repositories else None
    try:
        working_catalog = _container.resolve_catalog(
            settings, catalog=catalog, catalog_factory=catalog_factory
        )
        if use_grant_selection:
            result = _run_github_oauth_sync(
                settings,
                access_token=access_token,
                repositories=tuple(repositories),
                project_owner=project_owner,
                project_number=project_number,
                connector_id=connection.connector_id,
                catalog=working_catalog,
                vector_store=vector_store,
                vector_store_factory=vector_store_factory,
            )
        else:
            result = _run_legacy_combined_oauth_sync(
                settings,
                access_token=access_token,
                owner=owner,
                repo=repo,
                project_owner=project_owner,
                project_number=project_number,
                connector_id=connection.connector_id,
                catalog=working_catalog,
                vector_store=vector_store,
                vector_store_factory=vector_store_factory,
            )
    except ConnectorSyncError as error:
        if not isinstance(error.__cause__, ConnectorAuthError):
            raise
        if not connection.refresh_token:
            mark_github_reauth(tokens_store, error)
        try:
            grant = gateway.refresh(connection.refresh_token)
        except GitHubOAuthError as refresh_error:
            mark_github_reauth(tokens_store, refresh_error)
        access_token = grant.access_token
        refresh_token = grant.refresh_token or connection.refresh_token
        tokens_store.mutate(
            lambda current: None
            if current is None
            else replace(
                current,
                access_token=access_token,
                refresh_token=refresh_token,
                reauthorization_required=False,
                owner=owner,
                repo=repo,
                project_owner=project_owner,
                project_number=project_number,
            )
        )
        try:
            working_catalog = _container.resolve_catalog(
                settings, catalog=catalog, catalog_factory=catalog_factory
            )
            if use_grant_selection:
                result = _run_github_oauth_sync(
                    settings,
                    access_token=access_token,
                    repositories=tuple(repositories),
                    project_owner=project_owner,
                    project_number=project_number,
                    connector_id=connection.connector_id,
                    catalog=working_catalog,
                    vector_store=vector_store,
                    vector_store_factory=vector_store_factory,
                )
            else:
                result = _run_legacy_combined_oauth_sync(
                    settings,
                    access_token=access_token,
                    owner=owner,
                    repo=repo,
                    project_owner=project_owner,
                    project_number=project_number,
                    connector_id=connection.connector_id,
                    catalog=working_catalog,
                    vector_store=vector_store,
                    vector_store_factory=vector_store_factory,
                )
        except ConnectorSyncError as retry_error:
            if isinstance(retry_error.__cause__, ConnectorAuthError):
                mark_github_reauth(tokens_store, retry_error)
            raise
    synced_at = datetime.now(timezone.utc).isoformat()
    tokens_store.mutate(
        lambda current: None
        if current is None
        else replace(
            current,
            owner=owner,
            repo=repo,
            project_owner=project_owner,
            project_number=project_number,
            last_synced_at=synced_at,
            last_sync_new=result.ingested_count,
            last_sync_updated=(
                result.updated_count + result.metadata_updated_count
            ),
            last_sync_unchanged=result.skipped_count,
            last_sync_removed=result.removed_count,
            last_sync_failed=result.failed_count,
        )
    )
    return result


def _run_legacy_combined_oauth_sync(
    settings: Settings,
    *,
    access_token: str,
    owner: str | None,
    repo: str | None,
    project_owner: str | None,
    project_number: int | None,
    connector_id: str | None,
    catalog: DocumentCatalog,
    vector_store: VectorStore | None,
    vector_store_factory: Callable[[], VectorStore] | None,
) -> ConnectorSyncResponse:
    """Single connector sync from settings.github (pre-multi-repo path)."""
    from infrastructure.connectors.github.oauth import new_github_connector_id

    resolved_connector_id = (
        connector_id.strip()
        if isinstance(connector_id, str) and connector_id.strip()
        else settings.github.connector_id or new_github_connector_id()
    )
    oauth_settings = replace(
        settings,
        github=replace(
            settings.github,
            token=access_token,
            owner=owner,
            repo=repo,
            project_owner=project_owner,
            project_number=project_number,
            connector_id=resolved_connector_id,
        ),
    )
    try:
        connector = build_github_oauth_connector(
            oauth_settings,
            token=access_token,
        )
    except ConnectorError as error:
        raise GitHubConnectorSyncError(_GITHUB_SYNC_MESSAGE) from error
    return sync_github(
        oauth_settings,
        connector=connector,
        catalog=catalog,
        vector_store=vector_store,
        vector_store_factory=vector_store_factory,
    )


def _run_github_oauth_sync(
    settings: Settings,
    *,
    access_token: str,
    repositories: Sequence[GitHubRepoTarget],
    project_owner: str | None,
    project_number: int | None,
    connector_id: str | None,
    catalog: DocumentCatalog,
    vector_store: VectorStore | None,
    vector_store_factory: Callable[[], VectorStore] | None,
) -> ConnectorSyncResponse:
    from infrastructure.connectors.github.oauth import new_github_connector_id

    resolved_connector_id = (
        connector_id.strip()
        if isinstance(connector_id, str) and connector_id.strip()
        else settings.github.connector_id or new_github_connector_id()
    )
    outcomes: list[ConnectorSyncOutcome] = []
    auth_failure: ConnectorSyncError | None = None
    for target in repositories:
        try:
            result = _sync_one_repo_target(
                settings,
                access_token=access_token,
                target=target,
                connector_id=resolved_connector_id,
                catalog=catalog,
                vector_store=vector_store,
                vector_store_factory=vector_store_factory,
            )
            outcomes.extend(result.outcomes)
        except ConnectorSyncError as error:
            if isinstance(error.__cause__, ConnectorAuthError):
                auth_failure = error
                break
            # Non-auth failure: keep prior good docs for this identity; continue.
            continue
    if auth_failure is not None:
        raise auth_failure
    if project_owner and project_number is not None:
        result = _sync_project_issues(
            settings,
            access_token=access_token,
            project_owner=project_owner,
            project_number=project_number,
            connector_id=resolved_connector_id,
            catalog=catalog,
            vector_store=vector_store,
            vector_store_factory=vector_store_factory,
        )
        outcomes.extend(result.outcomes)
    if not repositories and not (project_owner and project_number is not None):
        raise GitHubSelectionRequiredError(
            "Select a GitHub repository or project before syncing."
        )
    return ConnectorSyncResponse(outcomes=tuple(outcomes))


def _sync_one_repo_target(
    settings: Settings,
    *,
    access_token: str,
    target: GitHubRepoTarget,
    connector_id: str,
    catalog: DocumentCatalog,
    vector_store: VectorStore | None,
    vector_store_factory: Callable[[], VectorStore] | None,
) -> ConnectorSyncResponse:
    extensions, globs = resolve_target_file_rules(
        target,
        workspace_extensions=settings.github.extensions,
    )
    include = target.include_prefixes or settings.github.include_paths
    exclude = target.exclude_prefixes or settings.github.exclude_paths
    oauth_settings = replace(
        settings,
        github=replace(
            settings.github,
            token=access_token,
            owner=target.owner,
            repo=target.repo,
            ref=target.ref or settings.github.ref,
            include_paths=tuple(include),
            exclude_paths=tuple(exclude),
            extensions=tuple(extensions),
            filename_globs=globs,
            project_owner=None,
            project_number=None,
            connector_id=connector_id,
        ),
    )
    try:
        connector = build_github_oauth_connector(
            oauth_settings,
            token=access_token,
        )
    except ConnectorError as error:
        raise GitHubConnectorSyncError(_GITHUB_SYNC_MESSAGE) from error
    return sync_github(
        oauth_settings,
        connector=connector,
        catalog=catalog,
        vector_store=vector_store,
        vector_store_factory=vector_store_factory,
        reconcile_source_id_prefixes=frozenset(
            {f"{target.owner}/{target.repo}:"}
        ),
    )


def _sync_project_issues(
    settings: Settings,
    *,
    access_token: str,
    project_owner: str,
    project_number: int,
    connector_id: str,
    catalog: DocumentCatalog,
    vector_store: VectorStore | None,
    vector_store_factory: Callable[[], VectorStore] | None,
) -> ConnectorSyncResponse:
    oauth_settings = replace(
        settings,
        github=replace(
            settings.github,
            token=access_token,
            owner=None,
            repo=None,
            project_owner=project_owner,
            project_number=project_number,
            connector_id=connector_id,
        ),
    )
    try:
        connector = build_github_oauth_connector(
            oauth_settings,
            token=access_token,
        )
    except ConnectorError as error:
        raise GitHubConnectorSyncError(_GITHUB_SYNC_MESSAGE) from error
    return sync_github(
        oauth_settings,
        connector=connector,
        catalog=catalog,
        vector_store=vector_store,
        vector_store_factory=vector_store_factory,
        reconcile_source_id_prefixes=frozenset({"issue:"}),
    )

