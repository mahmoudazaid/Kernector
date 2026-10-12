"""Read-only MCP tool listing projects and their confirmed associations."""

from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from application.project.projects import ListProjects
from domain.errors import ToolArgumentValidationError

TOOL_NAME = "core.project_list"
TOOL_DESCRIPTION = (
    "List the workspace's projects with their confirmed source associations "
    "(connector scope and context roles). Read-only."
)


class ProjectListArgs(BaseModel):
    """``core_project_list`` takes no arguments."""

    model_config = ConfigDict(extra="forbid")


class AssociationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_id: str
    scope_kind: str
    scope_value: str
    roles: list[str]


class ProjectOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    name: str
    slug: str
    confirmed_associations: list[AssociationOut]


class ProjectListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projects: list[ProjectOut]


class ProjectListTool:
    """Implements ``domain.ports.Tool`` over :class:`ListProjects`."""

    args_schema: type | None = ProjectListArgs
    output_schema: type | None = ProjectListResult

    def __init__(self, list_projects: ListProjects) -> None:
        self._list_projects = list_projects

    @property
    def name(self) -> str:
        return TOOL_NAME

    @property
    def description(self) -> str:
        return TOOL_DESCRIPTION

    def run(self, arguments: Mapping[str, object]) -> str:
        try:
            ProjectListArgs.model_validate(dict(arguments))
        except Exception as exc:
            raise ToolArgumentValidationError("Invalid project_list arguments") from exc
        result = ProjectListResult(
            projects=[
                ProjectOut(
                    project_id=overview.project.project_id,
                    name=overview.project.name,
                    slug=overview.project.slug,
                    confirmed_associations=[
                        AssociationOut(
                            connector_id=association.scope.connector_id,
                            scope_kind=association.scope.scope_kind,
                            scope_value=association.scope.scope_value,
                            roles=list(association.roles),
                        )
                        for association in overview.confirmed_associations
                    ],
                )
                for overview in self._list_projects.execute()
            ]
        )
        return json.dumps(result.model_dump(mode="json"), separators=(",", ":"))
