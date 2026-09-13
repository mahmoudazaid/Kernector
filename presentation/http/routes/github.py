"""Versioned GitHub connector routes."""

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from composition import GitHubStatus
from presentation.http.deps import (
    GitHubDisconnectDep,
    GitHubOAuthCallbackDep,
    GitHubOAuthStartDep,
    GitHubStatusDep,
    GitHubSyncDep,
)
from presentation.http.errors import problem_responses
from presentation.http.schemas import (
    GitHubLastSyncResponse,
    GitHubStatusResponse,
    GitHubSyncResponse,
    github_sync_response,
)

router = APIRouter(prefix="/api/v1", tags=["connectors"])


def _last_sync_response(status: GitHubStatus) -> GitHubLastSyncResponse | None:
    last = status.last_sync
    if last is None:
        return None
    return GitHubLastSyncResponse(
        synced_at=last.synced_at,
        new_count=last.new_count,
        updated_count=last.updated_count,
        unchanged_count=last.unchanged_count,
        removed_count=last.removed_count,
        failed_count=last.failed_count,
    )


def _status_response(status: GitHubStatus) -> GitHubStatusResponse:
    return GitHubStatusResponse(
        configured=status.configured,
        available=status.available,
        connected=status.connected,
        oauth_ready=status.oauth_ready,
        account_login=status.account_login,
        document_count=status.document_count,
        owner=status.owner,
        repo=status.repo,
        project_owner=status.project_owner,
        project_number=status.project_number,
        last_sync=_last_sync_response(status),
        reauthorization_required=status.reauthorization_required,
        connection_state=status.connection_state,
        sync_scope=status.sync_scope,
    )


@router.get(
    "/connectors/github",
    responses=problem_responses(405, 500),
)
def github_connector_status(
    status: GitHubStatusDep,
) -> GitHubStatusResponse:
    """Return presentation-safe GitHub PAT flags and user OAuth connection."""
    return _status_response(status)


@router.get(
    "/connectors/github/last-sync",
    responses=problem_responses(405, 500),
)
def github_connector_last_sync(
    status: GitHubStatusDep,
) -> GitHubLastSyncResponse | None:
    """Return the last persisted GitHub sync summary, if present."""
    return _last_sync_response(status)


@router.get(
    "/connectors/github/oauth/start",
    responses=problem_responses(405, 500),
)
def github_oauth_start(
    start: GitHubOAuthStartDep,
) -> RedirectResponse:
    """Issue CSRF state and redirect the browser to GitHub, or back to the Hub."""
    return RedirectResponse(url=start(), status_code=302)


@router.get(
    "/connectors/github/oauth/callback",
    responses=problem_responses(405, 500),
)
def github_oauth_callback(
    complete: GitHubOAuthCallbackDep,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Validate state, exchange the code server-side, and return to the Hub."""
    return RedirectResponse(
        url=complete(state, code, error),
        status_code=302,
    )


@router.post(
    "/connectors/github/sync",
    responses=problem_responses(405, 409, 500, 502),
)
def github_connector_sync(
    sync: GitHubSyncDep,
) -> GitHubSyncResponse:
    """Synchronize GitHub for the stored user OAuth grant."""
    return github_sync_response(sync())


@router.delete(
    "/connectors/github",
    status_code=204,
    responses=problem_responses(405, 409, 500),
)
def github_connector_disconnect(
    disconnect: GitHubDisconnectDep,
) -> None:
    """Revoke and delete the stored user grant. Indexed documents stay."""
    disconnect()
