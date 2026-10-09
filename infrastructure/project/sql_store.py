"""SQLite unit of work for projects, associations and components.

Tables live in the catalog database (migration 004). ``workspace_id`` is bound
at construction and is a parameter of every statement. Each write transaction
starts with ``BEGIN IMMEDIATE``, so writers are serialized and checks made
inside a transaction still hold at commit.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from domain.knowledge import SourceReference
from domain.project.errors import (
    AssociationExistsError,
    AssociationNotFoundError,
    ComponentNotFoundError,
    ProjectRecordVersionConflictError,
    ProjectSlugTakenError,
)
from domain.project.models import (
    AssociationState,
    ComponentMember,
    Project,
    ProjectComponent,
    SourceAssociation,
    SourceScope,
)
from infrastructure.catalog import _connection
from infrastructure.catalog.errors import CatalogError
from infrastructure.catalog.sql_schema import apply_migrations
from infrastructure.catalog.workspace import require_workspace_id


class ProjectStoreError(RuntimeError):
    """SQLite access to the project tables failed."""


_SCOPE_WHERE = "connector_id = ? AND scope_kind = ? AND scope_value = ?"
_ASSOCIATION_COLUMNS = (
    "project_id, connector_id, scope_kind, scope_value, roles, state, evidence, "
    "created_by, version"
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _scope_params(scope: SourceScope) -> tuple[str, str, str]:
    return (scope.connector_id, scope.scope_kind, scope.scope_value)


def _association_from_row(row: sqlite3.Row) -> SourceAssociation:
    return SourceAssociation(
        project_id=row["project_id"],
        scope=SourceScope(row["connector_id"], row["scope_kind"], row["scope_value"]),
        roles=tuple(json.loads(row["roles"])),
        state=AssociationState(row["state"]),
        evidence=tuple(
            SourceReference(item["source_id"], item["source_type"])
            for item in json.loads(row["evidence"])
        ),
        created_by=row["created_by"],
        version=row["version"],
    )


def _evidence_json(association: SourceAssociation) -> str:
    return json.dumps(
        [
            {"source_id": ref.source_id, "source_type": str(ref.source_type)}
            for ref in association.evidence
        ]
    )


def _check_version(row: sqlite3.Row | None, expected: int, missing: Exception) -> None:
    if row is None:
        raise missing
    if row["version"] != expected:
        raise ProjectRecordVersionConflictError(
            f"expected version {expected}, stored version is {row['version']}"
        )


class _Projects:
    def __init__(self, connection: sqlite3.Connection, workspace_id: str) -> None:
        self._connection = connection
        self._workspace_id = workspace_id

    def add(self, project: Project) -> None:
        now = _now()
        try:
            self._connection.execute(
                "INSERT INTO projects (workspace_id, project_id, name, slug, version, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    self._workspace_id,
                    project.project_id,
                    project.name,
                    project.slug,
                    project.version,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as error:
            if "slug" in str(error):
                raise ProjectSlugTakenError("slug is already used") from error
            raise ProjectStoreError("project_id already exists") from error

    def get(self, project_id: str) -> Project | None:
        row = self._connection.execute(
            "SELECT project_id, name, slug, version FROM projects "
            "WHERE workspace_id = ? AND project_id = ?",
            (self._workspace_id, project_id),
        ).fetchone()
        return None if row is None else Project(*row)

    def list(self) -> tuple[Project, ...]:
        rows = self._connection.execute(
            "SELECT project_id, name, slug, version FROM projects "
            "WHERE workspace_id = ? ORDER BY slug",
            (self._workspace_id,),
        ).fetchall()
        return tuple(Project(*row) for row in rows)


class _Associations:
    def __init__(self, connection: sqlite3.Connection, workspace_id: str) -> None:
        self._connection = connection
        self._workspace_id = workspace_id

    def add(self, association: SourceAssociation) -> None:
        now = _now()
        try:
            self._connection.execute(
                f"INSERT INTO source_associations (workspace_id, {_ASSOCIATION_COLUMNS}, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._workspace_id,
                    association.project_id,
                    *_scope_params(association.scope),
                    json.dumps(list(association.roles)),
                    str(association.state),
                    _evidence_json(association),
                    association.created_by,
                    association.version,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise AssociationExistsError(
                "the project already has an association for this scope"
            ) from error

    def get(self, project_id: str, scope: SourceScope) -> SourceAssociation | None:
        row = self._connection.execute(
            f"SELECT {_ASSOCIATION_COLUMNS} FROM source_associations "
            f"WHERE workspace_id = ? AND project_id = ? AND {_SCOPE_WHERE}",
            (self._workspace_id, project_id, *_scope_params(scope)),
        ).fetchone()
        return None if row is None else _association_from_row(row)

    def _locked_version(
        self, project_id: str, scope: SourceScope
    ) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT version FROM source_associations "
            f"WHERE workspace_id = ? AND project_id = ? AND {_SCOPE_WHERE}",
            (self._workspace_id, project_id, *_scope_params(scope)),
        ).fetchone()

    def update(
        self, association: SourceAssociation, *, expected_version: int
    ) -> SourceAssociation:
        _check_version(
            self._locked_version(association.project_id, association.scope),
            expected_version,
            AssociationNotFoundError("no association for this project and scope"),
        )
        new_version = expected_version + 1
        self._connection.execute(
            "UPDATE source_associations SET roles = ?, state = ?, evidence = ?, "
            "created_by = ?, version = ?, updated_at = ? "
            f"WHERE workspace_id = ? AND project_id = ? AND {_SCOPE_WHERE} "
            "AND version = ?",
            (
                json.dumps(list(association.roles)),
                str(association.state),
                _evidence_json(association),
                association.created_by,
                new_version,
                _now(),
                self._workspace_id,
                association.project_id,
                *_scope_params(association.scope),
                expected_version,
            ),
        )
        return replace(association, version=new_version)

    def delete(
        self, project_id: str, scope: SourceScope, *, expected_version: int
    ) -> None:
        _check_version(
            self._locked_version(project_id, scope),
            expected_version,
            AssociationNotFoundError("no association for this project and scope"),
        )
        self._connection.execute(
            "DELETE FROM source_associations "
            f"WHERE workspace_id = ? AND project_id = ? AND {_SCOPE_WHERE} "
            "AND version = ?",
            (self._workspace_id, project_id, *_scope_params(scope), expected_version),
        )

    def for_project(self, project_id: str) -> tuple[SourceAssociation, ...]:
        rows = self._connection.execute(
            f"SELECT {_ASSOCIATION_COLUMNS} FROM source_associations "
            "WHERE workspace_id = ? AND project_id = ? "
            "ORDER BY connector_id, scope_kind, scope_value",
            (self._workspace_id, project_id),
        ).fetchall()
        return tuple(_association_from_row(row) for row in rows)

    def for_scope(self, scope: SourceScope) -> tuple[SourceAssociation, ...]:
        rows = self._connection.execute(
            f"SELECT {_ASSOCIATION_COLUMNS} FROM source_associations "
            f"WHERE workspace_id = ? AND {_SCOPE_WHERE} ORDER BY project_id",
            (self._workspace_id, *_scope_params(scope)),
        ).fetchall()
        return tuple(_association_from_row(row) for row in rows)


class _Components:
    def __init__(self, connection: sqlite3.Connection, workspace_id: str) -> None:
        self._connection = connection
        self._workspace_id = workspace_id

    def _insert_members(self, component: ProjectComponent) -> None:
        try:
            self._connection.executemany(
                "INSERT INTO project_component_members (workspace_id, project_id, "
                "component_id, connector_id, scope_kind, scope_value, path_prefix, "
                "position) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        self._workspace_id,
                        component.project_id,
                        component.component_id,
                        *_scope_params(member.scope),
                        member.path_prefix,
                        position,
                    )
                    for position, member in enumerate(component.members)
                ],
            )
        except sqlite3.IntegrityError as error:
            raise AssociationExistsError(
                "a member with this scope and path prefix already exists in the project"
            ) from error

    def _delete_members(self, project_id: str, component_id: str) -> None:
        self._connection.execute(
            "DELETE FROM project_component_members "
            "WHERE workspace_id = ? AND project_id = ? AND component_id = ?",
            (self._workspace_id, project_id, component_id),
        )

    def add(self, component: ProjectComponent) -> None:
        now = _now()
        try:
            self._connection.execute(
                "INSERT INTO project_components (workspace_id, project_id, "
                "component_id, name, reason, version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._workspace_id,
                    component.project_id,
                    component.component_id,
                    component.name,
                    component.reason,
                    component.version,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise AssociationExistsError("component_id already exists") from error
        self._insert_members(component)

    def _members(
        self, project_id: str, component_id: str
    ) -> tuple[ComponentMember, ...]:
        rows = self._connection.execute(
            "SELECT connector_id, scope_kind, scope_value, path_prefix "
            "FROM project_component_members "
            "WHERE workspace_id = ? AND project_id = ? AND component_id = ? "
            "ORDER BY position",
            (self._workspace_id, project_id, component_id),
        ).fetchall()
        return tuple(
            ComponentMember(
                SourceScope(row["connector_id"], row["scope_kind"], row["scope_value"]),
                row["path_prefix"],
            )
            for row in rows
        )

    def _component(self, row: sqlite3.Row) -> ProjectComponent:
        return ProjectComponent(
            component_id=row["component_id"],
            project_id=row["project_id"],
            name=row["name"],
            members=self._members(row["project_id"], row["component_id"]),
            reason=row["reason"],
            version=row["version"],
        )

    def get(self, project_id: str, component_id: str) -> ProjectComponent | None:
        row = self._connection.execute(
            "SELECT project_id, component_id, name, reason, version "
            "FROM project_components "
            "WHERE workspace_id = ? AND project_id = ? AND component_id = ?",
            (self._workspace_id, project_id, component_id),
        ).fetchone()
        return None if row is None else self._component(row)

    def _locked_version(self, project_id: str, component_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT version FROM project_components "
            "WHERE workspace_id = ? AND project_id = ? AND component_id = ?",
            (self._workspace_id, project_id, component_id),
        ).fetchone()

    def update(
        self, component: ProjectComponent, *, expected_version: int
    ) -> ProjectComponent:
        _check_version(
            self._locked_version(component.project_id, component.component_id),
            expected_version,
            ComponentNotFoundError("no component with this id in the project"),
        )
        new_version = expected_version + 1
        self._connection.execute(
            "UPDATE project_components SET name = ?, reason = ?, version = ?, "
            "updated_at = ? WHERE workspace_id = ? AND project_id = ? "
            "AND component_id = ? AND version = ?",
            (
                component.name,
                component.reason,
                new_version,
                _now(),
                self._workspace_id,
                component.project_id,
                component.component_id,
                expected_version,
            ),
        )
        self._delete_members(component.project_id, component.component_id)
        self._insert_members(component)
        return replace(component, version=new_version)

    def delete(
        self, project_id: str, component_id: str, *, expected_version: int
    ) -> None:
        _check_version(
            self._locked_version(project_id, component_id),
            expected_version,
            ComponentNotFoundError("no component with this id in the project"),
        )
        self._delete_members(project_id, component_id)
        self._connection.execute(
            "DELETE FROM project_components WHERE workspace_id = ? AND project_id = ? "
            "AND component_id = ? AND version = ?",
            (self._workspace_id, project_id, component_id, expected_version),
        )

    def for_project(self, project_id: str) -> tuple[ProjectComponent, ...]:
        rows = self._connection.execute(
            "SELECT project_id, component_id, name, reason, version "
            "FROM project_components WHERE workspace_id = ? AND project_id = ? "
            "ORDER BY created_at, component_id",
            (self._workspace_id, project_id),
        ).fetchall()
        return tuple(self._component(row) for row in rows)


class _SqlTransaction:
    def __init__(self, connection: sqlite3.Connection, workspace_id: str) -> None:
        self.projects = _Projects(connection, workspace_id)
        self.associations = _Associations(connection, workspace_id)
        self.components = _Components(connection, workspace_id)


class SqlProjectStore:
    """Workspace-bound :class:`~domain.project.ports.ProjectUnitOfWork`."""

    def __init__(self, path: Path, workspace_id: str) -> None:
        self._workspace_id = require_workspace_id(workspace_id)
        self._path = path
        try:
            apply_migrations(path)
        except CatalogError as error:
            raise ProjectStoreError(
                f"could not apply project migrations at {path}"
            ) from error

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    @contextmanager
    def transaction(self) -> Iterator[_SqlTransaction]:
        with self._open("BEGIN IMMEDIATE") as tx:
            yield tx

    @contextmanager
    def read(self) -> Iterator[_SqlTransaction]:
        with self._open("BEGIN") as tx:
            yield tx

    @contextmanager
    def _open(self, begin: str) -> Iterator[_SqlTransaction]:
        try:
            connection = _connection.connect(self._path)
        except sqlite3.Error as error:
            raise ProjectStoreError(
                f"could not open project store at {self._path}"
            ) from error
        try:
            connection.execute(begin)
            yield _SqlTransaction(connection, self._workspace_id)
            connection.execute("COMMIT")
        except sqlite3.Error as error:
            _rollback(connection)
            raise ProjectStoreError(
                f"could not access project store at {self._path}"
            ) from error
        except BaseException:
            _rollback(connection)
            raise
        finally:
            connection.close()


def _rollback(connection: sqlite3.Connection) -> None:
    if connection.in_transaction:
        connection.execute("ROLLBACK")
