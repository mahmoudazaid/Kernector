"""Versioned Jira connector routes."""

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from composition import JiraSelection, JiraSiteItem, JiraStatus
from presentation.http.deps import (
    JiraDisconnectDep,
    JiraOAuthCallbackDep,
    JiraOAuthStartDep,
    JiraProjectListDep,
    JiraSelectionReadDep,
    JiraSelectionWriteDep,
    JiraSiteListDep,
    JiraSiteWriteDep,
    JiraStatusDep,
    JiraSyncDep,
)
from presentation.http.errors import problem_responses
from presentation.http.schemas import (
    JiraLastSyncResponse,
    JiraProjectItemResponse,
    JiraProjectPageResponse,
    JiraSelectionRequest,
    JiraSelectionResponse,
    JiraSiteListResponse,
    JiraSiteRequest,
    JiraSiteResponse,
    JiraStatusResponse,
    JiraSyncResponse,
    jira_sync_response,
)

router = APIRouter(prefix="/api/v1/connectors/jira", tags=["connectors"])


def _site_response(site: JiraSiteItem | None) -> JiraSiteResponse | None:
    if site is None:
        return None
    return JiraSiteResponse(
        instance_id=site.instance_id,
        cloud_id=site.cloud_id,
        name=site.name,
        url=site.url,
    )


def _last_sync_response(status: JiraStatus) -> JiraLastSyncResponse | None:
    last = status.last_sync
    if last is None:
        return None
    return JiraLastSyncResponse(
        synced_at=last.synced_at,
        new_count=last.new_count,
        updated_count=last.updated_count,
        unchanged_count=last.unchanged_count,
        removed_count=last.removed_count,
        failed_count=last.failed_count,
    )


def _selection_response(selection: JiraSelection) -> JiraSelectionResponse:
    return JiraSelectionResponse(
        site=_site_response(selection.site),
        project_keys=list(selection.project_keys),
        connector_id=selection.connector_id,
    )


@router.get("", responses=problem_responses(405, 500))
def jira_connector_status(status: JiraStatusDep) -> JiraStatusResponse:
    """Return the presentation-safe Jira connection, site, and projects."""
    return JiraStatusResponse(
        mode="data_center" if status.mode == "data_center" else "cloud",
        available=status.available,
        oauth_ready=status.oauth_ready,
        connected=status.connected,
        account_name=status.account_name,
        site=_site_response(status.site),
        project_keys=list(status.project_keys),
        document_count=status.document_count,
        last_sync=_last_sync_response(status),
        reauthorization_required=status.reauthorization_required,
        setup_required=status.setup_required,
        connection_state=status.connection_state,
        sync_scope=status.sync_scope,
    )


@router.get("/last-sync", responses=problem_responses(405, 500))
def jira_connector_last_sync(status: JiraStatusDep) -> JiraLastSyncResponse | None:
    """Return the last persisted Jira sync summary, if present."""
    return _last_sync_response(status)


@router.get("/oauth/start", responses=problem_responses(405, 409, 500))
def jira_oauth_start(start: JiraOAuthStartDep) -> RedirectResponse:
    """Issue CSRF state and redirect the browser to Atlassian, or back to the Hub."""
    return RedirectResponse(url=start(), status_code=302)


@router.get("/oauth/callback", responses=problem_responses(405, 409, 500))
def jira_oauth_callback(
    complete: JiraOAuthCallbackDep,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Validate state, exchange the code server-side, resolve sites, return to the Hub."""
    return RedirectResponse(url=complete(state, code, error), status_code=302)


@router.get("/sites", responses=problem_responses(405, 409, 500, 502))
def jira_connector_sites(list_sites: JiraSiteListDep) -> JiraSiteListResponse:
    """List Jira sites the stored grant can read."""
    return JiraSiteListResponse(
        items=[
            site_response
            for site in list_sites()
            if (site_response := _site_response(site)) is not None
        ]
    )


@router.put("/site", responses=problem_responses(405, 409, 422, 500, 502))
def jira_connector_put_site(
    body: JiraSiteRequest, save_site: JiraSiteWriteDep
) -> JiraSelectionResponse:
    """Select a Jira site. Switching sites removes its synced documents."""
    return _selection_response(save_site(cloud_id=body.cloud_id))


@router.get("/projects", responses=problem_responses(405, 409, 422, 500, 502))
def jira_connector_projects(
    list_projects: JiraProjectListDep,
    start_at: Annotated[int, Query(ge=0)] = 0,
) -> JiraProjectPageResponse:
    """List Jira projects for the Hub picker (Cloud: selected site; Data Center: server)."""
    page = list_projects(start_at=start_at)
    return JiraProjectPageResponse(
        items=[JiraProjectItemResponse(key=p.key, name=p.name) for p in page.items],
        next_start_at=page.next_start_at,
    )


@router.get("/selection", responses=problem_responses(405, 409, 500))
def jira_connector_get_selection(
    load_selection: JiraSelectionReadDep,
) -> JiraSelectionResponse:
    """Return the saved Jira site and project keys."""
    return _selection_response(load_selection())


@router.put("/selection", responses=problem_responses(405, 409, 422, 500, 502))
def jira_connector_put_selection(
    body: JiraSelectionRequest, save_selection: JiraSelectionWriteDep
) -> JiraSelectionResponse:
    """Validate project access and replace the selection; deselected projects are purged."""
    return _selection_response(save_selection(project_keys=body.project_keys))


@router.post("/sync", responses=problem_responses(405, 409, 500, 502))
def jira_connector_sync(sync: JiraSyncDep) -> JiraSyncResponse:
    """Synchronize the selected Jira projects into the knowledge base."""
    return jira_sync_response(sync())


@router.delete("", status_code=204, responses=problem_responses(405, 409, 500))
def jira_connector_disconnect(disconnect: JiraDisconnectDep) -> None:
    """Delete the stored Jira connection state. Synced Jira documents are removed."""
    disconnect()
