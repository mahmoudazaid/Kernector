"""HTTP routes for project identity and source associations (#372 / #447)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response

from application.project.associations import (
    AssociateSourceRequest,
    ConfirmAssociationRequest,
    RemoveAssociationRequest,
)
from application.project.projects import CreateProjectRequest
from composition.auth import build_auth_store
from domain.project.access import ProjectAccessCaller, ProjectAccessPolicy
from domain.project.models import SourceScope
from presentation.http.deps import (
    ListArtifactRelationshipsDep,
    ProjectAccessPolicyDep,
    ProjectUseCasesDep,
    TrustedCallerDep,
    get_settings,
)
from presentation.http.errors import problem_responses
from presentation.http.schemas import (
    AssociateSourceBody,
    ConfirmAssociationBody,
    CreateProjectBody,
    ProjectAssociationResponse,
    ProjectDetailResponse,
    ProjectResponse,
    RelationshipResponse,
    project_association_response,
    project_detail_response,
    project_response,
    relationship_response,
)

router = APIRouter(prefix="/api/v1", tags=["projects"])

OPERATOR_ACTOR = "operator"


def _require_project_access(
    caller: ProjectAccessCaller,
    policy: ProjectAccessPolicy,
    project_id: str,
) -> None:
    """Fail closed with sanitized 404 when the project is not readable.

    ``ProjectAccessPolicy.can_read`` is a project-scope isolation gate under
    #447, not write/action permission (#456).
    """
    if not policy.can_read(caller, project_id):
        raise HTTPException(status_code=404, detail="Not found.")


@router.post(
    "/projects",
    status_code=201,
    responses=problem_responses(401, 403, 409, 422, 500),
)
def create_project(
    body: CreateProjectBody,
    caller: TrustedCallerDep,
    use_cases: ProjectUseCasesDep,
) -> ProjectResponse:
    """Create a project in the trusted workspace and grant the caller access."""
    project = use_cases.create.execute(
        CreateProjectRequest(name=body.name, slug=body.slug)
    )
    store = build_auth_store(get_settings())
    store.grant_project(
        caller.principal.user_id, caller.workspace_id, project.project_id
    )
    return project_response(project)


@router.get(
    "/projects",
    responses=problem_responses(401, 403, 500),
)
def list_projects(
    caller: TrustedCallerDep,
    policy: ProjectAccessPolicyDep,
    use_cases: ProjectUseCasesDep,
) -> list[ProjectResponse]:
    """List projects the trusted caller may read in the bound workspace."""
    allowed = set(policy.readable_projects(caller))
    return [
        project_response(item.project)
        for item in use_cases.list.execute()
        if item.project.project_id in allowed
    ]


@router.get(
    "/projects/{project_id}",
    responses=problem_responses(401, 403, 404, 422, 500),
)
def get_project(
    project_id: str,
    caller: TrustedCallerDep,
    policy: ProjectAccessPolicyDep,
    use_cases: ProjectUseCasesDep,
) -> ProjectDetailResponse:
    """Return a project with its associations and components."""
    _require_project_access(caller, policy, project_id)
    return project_detail_response(use_cases.get.execute(project_id))


@router.post(
    "/projects/{project_id}/sources",
    status_code=201,
    responses=problem_responses(401, 403, 404, 409, 422, 500),
)
def associate_source(
    project_id: str,
    body: AssociateSourceBody,
    caller: TrustedCallerDep,
    policy: ProjectAccessPolicyDep,
    use_cases: ProjectUseCasesDep,
) -> ProjectAssociationResponse:
    """Explicitly associate a connector scope with the project."""
    _require_project_access(caller, policy, project_id)
    association = use_cases.associate.execute(
        AssociateSourceRequest(
            project_id=project_id,
            scope=SourceScope(body.connector_id, body.scope_kind, body.scope_value),
            roles=tuple(body.roles),
            created_by=OPERATOR_ACTOR,
            acknowledged_shared_with=frozenset(body.acknowledged_shared_with),
        )
    )
    return project_association_response(association)


@router.post(
    "/projects/{project_id}/sources/confirm",
    responses=problem_responses(401, 403, 404, 409, 422, 500),
)
def confirm_association(
    project_id: str,
    body: ConfirmAssociationBody,
    caller: TrustedCallerDep,
    policy: ProjectAccessPolicyDep,
    use_cases: ProjectUseCasesDep,
) -> ProjectAssociationResponse:
    """Confirm a suggested or rejected association."""
    _require_project_access(caller, policy, project_id)
    association = use_cases.confirm.execute(
        ConfirmAssociationRequest(
            project_id=project_id,
            scope=SourceScope(body.connector_id, body.scope_kind, body.scope_value),
            expected_version=body.expected_version,
            roles=None if body.roles is None else tuple(body.roles),
            acknowledged_shared_with=frozenset(body.acknowledged_shared_with),
        )
    )
    return project_association_response(association)


@router.delete(
    "/projects/{project_id}/sources",
    status_code=204,
    responses=problem_responses(401, 403, 404, 409, 422, 500),
)
def remove_association(
    project_id: str,
    caller: TrustedCallerDep,
    policy: ProjectAccessPolicyDep,
    use_cases: ProjectUseCasesDep,
    connector_id: str = Query(min_length=1, max_length=512),
    scope_kind: str = Query(min_length=1, max_length=64),
    scope_value: str = Query(min_length=1, max_length=512),
    expected_version: int = Query(ge=1),
) -> Response:
    """Remove an association; resolution excludes it immediately."""
    _require_project_access(caller, policy, project_id)
    use_cases.remove.execute(
        RemoveAssociationRequest(
            project_id=project_id,
            scope=SourceScope(connector_id, scope_kind, scope_value),
            expected_version=expected_version,
        )
    )
    return Response(status_code=204)


@router.get(
    "/projects/{project_id}/artifacts/{key:path}/relationships",
    responses=problem_responses(401, 403, 404, 422, 500),
)
def list_artifact_relationships(
    project_id: str,
    key: str,
    caller: TrustedCallerDep,
    policy: ProjectAccessPolicyDep,
    list_relationships: ListArtifactRelationshipsDep,
    origin: str | None = Query(default=None),
    verification: str | None = Query(default=None),
    freshness: str | None = Query(default=None),
) -> list[RelationshipResponse]:
    """List evidence-backed relationships for an artifact key in a project."""
    _require_project_access(caller, policy, project_id)
    filters = {
        name: value
        for name, value in (
            ("origin", origin),
            ("verification", verification),
            ("freshness", freshness),
        )
        if value is not None
    }
    views = list_relationships.execute(
        project_id, key, filters=filters or None
    )
    return [relationship_response(view) for view in views]
