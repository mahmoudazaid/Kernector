"""HTTP routes for project identity and source associations (#372)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response

from application.project.associations import (
    AssociateSourceRequest,
    ConfirmAssociationRequest,
    RemoveAssociationRequest,
)
from application.project.projects import CreateProjectRequest
from domain.project.models import SourceScope
from presentation.http.deps import ProjectUseCasesDep
from presentation.http.errors import problem_responses
from presentation.http.schemas import (
    AssociateSourceBody,
    ConfirmAssociationBody,
    CreateProjectBody,
    ProjectAssociationResponse,
    ProjectDetailResponse,
    ProjectResponse,
    project_association_response,
    project_detail_response,
    project_response,
)

router = APIRouter(prefix="/api/v1", tags=["projects"])

OPERATOR_ACTOR = "operator"


@router.post(
    "/projects",
    status_code=201,
    responses=problem_responses(409, 422, 500),
)
def create_project(
    body: CreateProjectBody, use_cases: ProjectUseCasesDep
) -> ProjectResponse:
    """Create a project in the bound workspace."""
    project = use_cases.create.execute(
        CreateProjectRequest(name=body.name, slug=body.slug)
    )
    return project_response(project)


@router.get("/projects", responses=problem_responses(500))
def list_projects(use_cases: ProjectUseCasesDep) -> list[ProjectResponse]:
    """List the bound workspace's projects."""
    return [project_response(item.project) for item in use_cases.list.execute()]


@router.get(
    "/projects/{project_id}",
    responses=problem_responses(404, 422, 500),
)
def get_project(
    project_id: str, use_cases: ProjectUseCasesDep
) -> ProjectDetailResponse:
    """Return a project with its associations and components."""
    return project_detail_response(use_cases.get.execute(project_id))


@router.post(
    "/projects/{project_id}/sources",
    status_code=201,
    responses=problem_responses(404, 409, 422, 500),
)
def associate_source(
    project_id: str, body: AssociateSourceBody, use_cases: ProjectUseCasesDep
) -> ProjectAssociationResponse:
    """Explicitly associate a connector scope with the project."""
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
    responses=problem_responses(404, 409, 422, 500),
)
def confirm_association(
    project_id: str, body: ConfirmAssociationBody, use_cases: ProjectUseCasesDep
) -> ProjectAssociationResponse:
    """Confirm a suggested or rejected association."""
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
    responses=problem_responses(404, 409, 422, 500),
)
def remove_association(
    project_id: str,
    use_cases: ProjectUseCasesDep,
    connector_id: str = Query(min_length=1, max_length=512),
    scope_kind: str = Query(min_length=1, max_length=64),
    scope_value: str = Query(min_length=1, max_length=512),
    expected_version: int = Query(ge=1),
) -> Response:
    """Remove an association; resolution excludes it immediately."""
    use_cases.remove.execute(
        RemoveAssociationRequest(
            project_id=project_id,
            scope=SourceScope(connector_id, scope_kind, scope_value),
            expected_version=expected_version,
        )
    )
    return Response(status_code=204)
