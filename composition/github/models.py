"""GitHub connector DTOs returned to presentation."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GitHubLastSync:
    """Last HTTP OAuth sync counts persisted with the user grant."""

    synced_at: str
    new_count: int
    updated_count: int
    unchanged_count: int
    removed_count: int
    failed_count: int


@dataclass(frozen=True, slots=True)
class GitHubStatus:
    """GitHub PAT presence, extra availability, and user OAuth connection."""

    configured: bool
    available: bool
    connected: bool = False
    oauth_ready: bool = False
    account_login: str | None = None
    document_count: int = 0
    owner: str | None = None
    repo: str | None = None
    project_owner: str | None = None
    project_number: int | None = None
    last_sync: GitHubLastSync | None = None
    reauthorization_required: bool = False
    connection_state: str = "disconnected"
    sync_scope: str | None = None
    setup_required: bool = False


@dataclass(frozen=True, slots=True)
class GitHubRepoItem:
    """One repository row for the Hub picker."""

    owner: str
    name: str
    full_name: str
    private: bool = False


@dataclass(frozen=True, slots=True)
class GitHubRepoPage:
    """One page of repositories for the Hub picker."""

    items: tuple[GitHubRepoItem, ...]
    has_next: bool = False
    page: int = 1


@dataclass(frozen=True, slots=True)
class GitHubProjectItem:
    """One ProjectV2 row for the Hub picker."""

    owner_login: str
    number: int
    title: str


@dataclass(frozen=True, slots=True)
class GitHubProjectPage:
    """One page of ProjectV2 projects for the Hub picker."""

    items: tuple[GitHubProjectItem, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class GitHubSelection:
    """Saved Hub sync targets: optional repository and/or ProjectV2."""

    owner: str | None = None
    repo: str | None = None
    project_owner: str | None = None
    project_number: int | None = None
    connector_id: str | None = None
