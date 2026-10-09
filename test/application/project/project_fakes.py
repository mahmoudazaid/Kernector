"""In-memory ProjectUnitOfWork with copy-on-enter semantics and failure injection."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from domain.knowledge import CatalogDocument, CatalogStatus, SourceReference
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


class InjectedFailure(RuntimeError):
    """Raised by a fake repository method listed in ``fail_on``."""


@dataclass
class _State:
    projects: dict[str, Project] = field(default_factory=dict)
    associations: dict[tuple[str, SourceScope], SourceAssociation] = field(
        default_factory=dict
    )
    components: dict[tuple[str, str], ProjectComponent] = field(default_factory=dict)


def _check(current: int | None, expected: int, missing: Exception) -> None:
    if current is None:
        raise missing
    if current != expected:
        raise ProjectRecordVersionConflictError("version conflict")


class _Tx:
    def __init__(self, state: _State, fail_on: set[str]) -> None:
        self._state = state
        self._fail_on = fail_on
        self.projects = _Projects(self)
        self.associations = _Associations(self)
        self.components = _Components(self)

    def maybe_fail(self, operation: str) -> None:
        if operation in self._fail_on:
            raise InjectedFailure(operation)


class _Projects:
    def __init__(self, tx: _Tx) -> None:
        self._tx = tx

    def add(self, project: Project) -> None:
        self._tx.maybe_fail("projects.add")
        state = self._tx._state
        if any(p.slug == project.slug for p in state.projects.values()):
            raise ProjectSlugTakenError("slug is already used")
        state.projects[project.project_id] = project

    def get(self, project_id: str) -> Project | None:
        return self._tx._state.projects.get(project_id)

    def list(self) -> tuple[Project, ...]:
        return tuple(sorted(self._tx._state.projects.values(), key=lambda p: p.slug))


class _Associations:
    def __init__(self, tx: _Tx) -> None:
        self._tx = tx

    @property
    def _rows(self) -> dict[tuple[str, SourceScope], SourceAssociation]:
        return self._tx._state.associations

    def add(self, association: SourceAssociation) -> None:
        self._tx.maybe_fail("associations.add")
        key = (association.project_id, association.scope)
        if key in self._rows:
            raise AssociationExistsError("association exists")
        self._rows[key] = association

    def get(self, project_id: str, scope: SourceScope) -> SourceAssociation | None:
        return self._rows.get((project_id, scope))

    def update(
        self, association: SourceAssociation, *, expected_version: int
    ) -> SourceAssociation:
        self._tx.maybe_fail("associations.update")
        key = (association.project_id, association.scope)
        current = self._rows.get(key)
        _check(
            None if current is None else current.version,
            expected_version,
            AssociationNotFoundError("missing"),
        )
        stored = replace(association, version=expected_version + 1)
        self._rows[key] = stored
        return stored

    def delete(
        self, project_id: str, scope: SourceScope, *, expected_version: int
    ) -> None:
        self._tx.maybe_fail("associations.delete")
        current = self._rows.get((project_id, scope))
        _check(
            None if current is None else current.version,
            expected_version,
            AssociationNotFoundError("missing"),
        )
        del self._rows[(project_id, scope)]

    def for_project(self, project_id: str) -> tuple[SourceAssociation, ...]:
        return tuple(a for (pid, _), a in self._rows.items() if pid == project_id)

    def for_scope(self, scope: SourceScope) -> tuple[SourceAssociation, ...]:
        return tuple(a for (_, s), a in self._rows.items() if s == scope)


class _Components:
    def __init__(self, tx: _Tx) -> None:
        self._tx = tx

    @property
    def _rows(self) -> dict[tuple[str, str], ProjectComponent]:
        return self._tx._state.components

    def _check_members(self, component: ProjectComponent) -> None:
        taken = {
            member
            for (pid, cid), other in self._rows.items()
            if pid == component.project_id and cid != component.component_id
            for member in other.members
        }
        if taken & set(component.members):
            raise AssociationExistsError("member exists")

    def add(self, component: ProjectComponent) -> None:
        self._tx.maybe_fail("components.add")
        key = (component.project_id, component.component_id)
        if key in self._rows:
            raise AssociationExistsError("component exists")
        self._check_members(component)
        self._rows[key] = component

    def get(self, project_id: str, component_id: str) -> ProjectComponent | None:
        return self._rows.get((project_id, component_id))

    def update(
        self, component: ProjectComponent, *, expected_version: int
    ) -> ProjectComponent:
        self._tx.maybe_fail("components.update")
        key = (component.project_id, component.component_id)
        current = self._rows.get(key)
        _check(
            None if current is None else current.version,
            expected_version,
            ComponentNotFoundError("missing"),
        )
        self._check_members(component)
        stored = replace(component, version=expected_version + 1)
        self._rows[key] = stored
        return stored

    def delete(
        self, project_id: str, component_id: str, *, expected_version: int
    ) -> None:
        self._tx.maybe_fail("components.delete")
        current = self._rows.get((project_id, component_id))
        _check(
            None if current is None else current.version,
            expected_version,
            ComponentNotFoundError("missing"),
        )
        del self._rows[(project_id, component_id)]

    def for_project(self, project_id: str) -> tuple[ProjectComponent, ...]:
        return tuple(c for (pid, _), c in self._rows.items() if pid == project_id)


class InMemoryProjectStore:
    """Commits a copy of the state only when the transaction exits cleanly."""

    def __init__(self) -> None:
        self._state = _State()
        self.fail_on: set[str] = set()

    @contextmanager
    def transaction(self) -> Iterator[_Tx]:
        working = copy.deepcopy(self._state)
        yield _Tx(working, self.fail_on)
        self._state = working

    @contextmanager
    def read(self) -> Iterator[_Tx]:
        yield _Tx(copy.deepcopy(self._state), set())


def catalog_document(
    source_id: str, source_type: str, connector_id: str | None
) -> CatalogDocument:
    stamp = datetime(2026, 10, 1, tzinfo=UTC)
    return CatalogDocument(
        reference=SourceReference(source_id, source_type),
        file_name=source_id.rsplit("/", 1)[-1] or "doc",
        title=None,
        content_format="markdown",
        status=CatalogStatus.READY,
        created_at=stamp,
        updated_at=stamp,
        chunk_count=1,
        error=None,
        connector_id=connector_id,
    )


def confirmed(
    project_id: str, scope: SourceScope, roles: tuple[str, ...] = ()
) -> SourceAssociation:
    return SourceAssociation(
        project_id, scope, roles, AssociationState.CONFIRMED, (), "operator", 1
    )


def member(scope: SourceScope, prefix: str = "") -> ComponentMember:
    return ComponentMember(scope, prefix)
