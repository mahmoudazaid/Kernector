"""GitHub picker: repository/project listing and the saved selection."""

from collections.abc import (
    Callable,
    Mapping,
    Sequence,
)  # Sequence used by repositories param
from dataclasses import replace

from application.errors import (
    GitHubNotConnectedError,
    GitHubReauthorizationRequiredError,
    InputRejectedError,
)
from composition.errors import GitHubConnectorError
from composition.github.connection import (
    github_picker_client,
    mark_github_reauth,
    purge_github_dropped_selection_docs,
    require_github_grant,
)
from composition.github.models import (
    GitHubProjectItem,
    GitHubProjectPage,
    GitHubRepoItem,
    GitHubRepoPage,
    GitHubRepoTarget,
    GitHubSelection,
)
from composition.github.targets import (
    normalize_and_validate_targets,
    repositories_from_connection,
    target_to_payload,
)
from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
)
from domain.ports import (
    DocumentCatalog,
    VectorStore,
)
from infrastructure.config import Settings


_GITHUB_REQUEST_MESSAGE = "The GitHub request failed."


def list_github_repositories(
    settings: Settings,
    *,
    page: int = 1,
    connection_store=None,
    client_factory=None,
) -> GitHubRepoPage:
    """List repositories visible to the stored GitHub grant for the Hub picker."""
    _tokens_store, connection = require_github_grant(
        settings, connection_store=connection_store
    )
    client = github_picker_client(
        settings,
        access_token=connection.access_token,
        client_factory=client_factory,
    )
    try:
        payload = client.list_repositories(page=page)
    except ConnectorAuthError as error:
        mark_github_reauth(_tokens_store, error)
    except ConnectorError as error:
        raise GitHubConnectorError(_GITHUB_REQUEST_MESSAGE) from error
    raw_items = payload.get("items")
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        raise GitHubConnectorError(_GITHUB_REQUEST_MESSAGE)
    items: list[GitHubRepoItem] = []
    for row in raw_items:
        if not isinstance(row, Mapping):
            continue
        owner = row.get("owner")
        name = row.get("name")
        full_name = row.get("full_name")
        if (
            isinstance(owner, str)
            and owner.strip()
            and isinstance(name, str)
            and name.strip()
            and isinstance(full_name, str)
            and full_name.strip()
        ):
            items.append(
                GitHubRepoItem(
                    owner=owner.strip(),
                    name=name.strip(),
                    full_name=full_name.strip(),
                    private=bool(row.get("private")),
                )
            )
    return GitHubRepoPage(
        items=tuple(items),
        has_next=bool(payload.get("has_next")),
        page=page,
    )


def list_github_projects(
    settings: Settings,
    *,
    owner_login: str,
    after: str | None = None,
    connection_store=None,
    client_factory=None,
) -> GitHubProjectPage:
    """List ProjectV2 projects for a login using the stored GitHub grant."""
    login = owner_login.strip()
    if not login:
        raise InputRejectedError("A project owner login is required.")
    _tokens_store, connection = require_github_grant(
        settings, connection_store=connection_store
    )
    client = github_picker_client(
        settings,
        access_token=connection.access_token,
        client_factory=client_factory,
    )
    try:
        payload = client.list_projects(login, after=after)
    except ConnectorAuthError as error:
        mark_github_reauth(_tokens_store, error)
    except ConnectorError as error:
        raise GitHubConnectorError(_GITHUB_REQUEST_MESSAGE) from error
    raw_items = payload.get("items")
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        raise GitHubConnectorError(_GITHUB_REQUEST_MESSAGE)
    items: list[GitHubProjectItem] = []
    for row in raw_items:
        if not isinstance(row, Mapping):
            continue
        number = row.get("number")
        title = row.get("title")
        row_owner = row.get("owner_login")
        if (
            isinstance(number, int)
            and isinstance(title, str)
            and title.strip()
            and isinstance(row_owner, str)
            and row_owner.strip()
        ):
            items.append(
                GitHubProjectItem(
                    owner_login=row_owner.strip(),
                    number=number,
                    title=title.strip(),
                )
            )
    next_cursor = payload.get("next_cursor")
    return GitHubProjectPage(
        items=tuple(items),
        next_cursor=next_cursor if isinstance(next_cursor, str) and next_cursor else None,
    )


def get_github_selection(
    settings: Settings,
    *,
    connection_store=None,
) -> GitHubSelection:
    """Return the saved repository targets and optional ProjectV2 selection."""
    _tokens_store, connection = require_github_grant(
        settings, connection_store=connection_store
    )
    repositories = repositories_from_connection(
        owner=connection.owner,
        repo=connection.repo,
        repositories=connection.repositories,
    )
    primary = repositories[0] if repositories else None
    return GitHubSelection(
        owner=primary.owner if primary else None,
        repo=primary.repo if primary else None,
        project_owner=connection.project_owner,
        project_number=connection.project_number,
        connector_id=connection.connector_id,
        repositories=repositories,
    )


def put_github_selection(
    settings: Settings,
    *,
    owner: str | None = None,
    repo: str | None = None,
    project_owner: str | None = None,
    project_number: int | None = None,
    repositories: Sequence[GitHubRepoTarget] | None = None,
    connection_store=None,
    client_factory=None,
    catalog: DocumentCatalog | None = None,
    catalog_factory: Callable[[], DocumentCatalog] | None = None,
    vector_store: VectorStore | None = None,
    vector_store_factory: Callable[[], VectorStore] | None = None,
) -> GitHubSelection:
    """Validate access and atomically replace the saved GitHub selection.

    When a previously selected repository identity and/or project is cleared or
    replaced, synced GitHub catalog rows for the dropped scope(s) are removed.
    Sync-config-only changes for an existing identity do not purge that
    identity's documents at put time (reconcile happens on sync).
    """
    owner_clean = (
        owner.strip() if isinstance(owner, str) and owner.strip() else None
    )
    repo_clean = (
        repo.strip() if isinstance(repo, str) and repo.strip() else None
    )
    if repositories is None and (owner_clean is None) != (repo_clean is None):
        raise InputRejectedError(
            "Repository owner and name must be set together."
        )
    targets = normalize_and_validate_targets(
        repositories,
        owner=owner_clean,
        repo=repo_clean,
        max_repositories=settings.github.max_repositories,
    )
    primary = targets[0] if targets else None
    owner_clean = primary.owner if primary else None
    repo_clean = primary.repo if primary else None
    project_owner_clean = (
        project_owner.strip() if isinstance(project_owner, str) else None
    ) or None
    if project_number is not None and (
        not isinstance(project_number, int)
        or isinstance(project_number, bool)
        or project_number < 1
    ):
        raise InputRejectedError("A project number must be a positive integer.")
    if (project_owner_clean is None) != (project_number is None):
        raise InputRejectedError(
            "Project owner and project number must be set together."
        )
    tokens_store, connection = require_github_grant(
        settings, connection_store=connection_store
    )
    previous_targets = repositories_from_connection(
        owner=connection.owner,
        repo=connection.repo,
        repositories=connection.repositories,
    )
    previous_project_owner = connection.project_owner
    previous_project_number = connection.project_number
    if targets or project_owner_clean is not None:
        client = github_picker_client(
            settings,
            access_token=connection.access_token,
            client_factory=client_factory,
        )
        try:
            for target in targets:
                client.get_repository(target.owner, target.repo)
            if project_owner_clean is not None and project_number is not None:
                client.resolve_project_v2_id(
                    project_owner_clean, project_number
                )
        except ConnectorAuthError as error:
            mark_github_reauth(tokens_store, error)
        except ConnectorError as error:
            raise InputRejectedError(
                "The selected GitHub repository or project is inaccessible."
            ) from error

    repo_payloads = tuple(target_to_payload(target) for target in targets)

    def _apply(current):
        from infrastructure.connectors.github.oauth import with_connector_id

        if current is None:
            raise GitHubNotConnectedError("GitHub is not connected")
        if current.reauthorization_required:
            raise GitHubReauthorizationRequiredError(
                "GitHub authorization was revoked"
            )
        updated = replace(
            current,
            owner=owner_clean,
            repo=repo_clean,
            project_owner=project_owner_clean,
            project_number=project_number,
            repositories=repo_payloads,
        )
        return with_connector_id(updated, preferred=settings.github.connector_id)

    tokens_store.mutate(_apply)
    saved = tokens_store.load()
    assert saved is not None
    purge_github_dropped_selection_docs(
        settings,
        previous_repositories=previous_targets,
        new_repositories=targets,
        previous_project_owner=previous_project_owner,
        previous_project_number=previous_project_number,
        new_project_owner=project_owner_clean,
        new_project_number=project_number,
        connector_id=saved.connector_id,
        catalog=catalog,
        catalog_factory=catalog_factory,
        vector_store=vector_store,
        vector_store_factory=vector_store_factory,
    )
    return GitHubSelection(
        owner=owner_clean,
        repo=repo_clean,
        project_owner=project_owner_clean,
        project_number=project_number,
        connector_id=saved.connector_id,
        repositories=targets,
    )
