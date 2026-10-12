"""Project components: defaults, path-prefix resolution and operator edits.

Every mutation runs in one transaction with compare-and-swap on each touched
component. Resolution joins members to ``confirmed`` associations, so a
removed or unconfirmed association never yields a component.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from application.project.projects import require_project
from application.project.resolve import document_scopes
from domain.knowledge import SourceReference
from domain.ports import DocumentCatalog
from domain.project.errors import (
    AssociationExistsError,
    ComponentNotFoundError,
    ProjectInputError,
    ProjectRecordVersionConflictError,
)
from domain.project.models import (
    COMPONENT_REASON_ASSOCIATION_DEFAULT,
    COMPONENT_REASON_OPERATOR,
    AssociationState,
    ComponentMember,
    ComponentResolution,
    ComponentResolutionStatus,
    ProjectComponent,
    SourceScope,
    new_component_id,
)
from domain.project.paths import (
    is_valid_path,
    normalize_path_prefix,
    prefix_depth,
    prefix_matches,
)
from domain.project.ports import (
    ProjectTransaction,
    ProjectUnitOfWork,
    SourceScopeResolver,
)


def ensure_default_component(
    tx: ProjectTransaction,
    project_id: str,
    scope: SourceScope,
    component_forming_kinds: frozenset[str],
    new_id: Callable[[], str],
) -> None:
    """Give a component-forming scope its whole-scope component once."""
    if scope.scope_kind not in component_forming_kinds:
        return
    for component in tx.components.for_project(project_id):
        if any(member.scope == scope for member in component.members):
            return
    tx.components.add(
        ProjectComponent(
            component_id=new_id(),
            project_id=project_id,
            name=scope.scope_value,
            members=(ComponentMember(scope, ""),),
            reason=COMPONENT_REASON_ASSOCIATION_DEFAULT,
            version=1,
        )
    )


def remove_scope_members(
    tx: ProjectTransaction, project_id: str, scope: SourceScope
) -> None:
    """Drop the scope's members; delete components left without members."""
    for component in tx.components.for_project(project_id):
        kept = tuple(m for m in component.members if m.scope != scope)
        if len(kept) == len(component.members):
            continue
        if kept:
            tx.components.update(
                replace(component, members=kept), expected_version=component.version
            )
        else:
            tx.components.delete(
                project_id, component.component_id, expected_version=component.version
            )


def _require_component(
    tx: ProjectTransaction, project_id: str, component_id: str, expected_version: int
) -> ProjectComponent:
    component = tx.components.get(project_id, component_id)
    if component is None:
        raise ComponentNotFoundError("no component with this id in the project")
    if component.version != expected_version:
        raise ProjectRecordVersionConflictError(
            f"expected version {expected_version}, "
            f"stored version is {component.version}"
        )
    return component


def _owner_of(
    tx: ProjectTransaction, project_id: str, member: ComponentMember
) -> ProjectComponent | None:
    for component in tx.components.for_project(project_id):
        if member in component.members:
            return component
    return None


@dataclass(frozen=True, slots=True)
class AssignComponentRequest:
    project_id: str
    component_id: str
    expected_version: int
    member: ComponentMember
    source_component_id: str | None = None
    source_expected_version: int | None = None


class AssignComponent:
    """Add a member to a component, moving it from its current component."""

    def __init__(self, *, store: ProjectUnitOfWork) -> None:
        self._store = store

    def execute(self, request: AssignComponentRequest) -> ProjectComponent:
        """Raises:
        ProjectNotFoundError, ComponentNotFoundError, ProjectInputError,
        AssociationExistsError, ProjectRecordVersionConflictError.
        """
        with self._store.transaction() as tx:
            require_project(tx, request.project_id)
            target = _require_component(
                tx, request.project_id, request.component_id, request.expected_version
            )
            if tx.associations.get(request.project_id, request.member.scope) is None:
                raise ProjectInputError("the project has no association for this scope")
            owner = _owner_of(tx, request.project_id, request.member)
            if owner is not None and owner.component_id == target.component_id:
                raise AssociationExistsError("the component already has this member")
            if owner is not None:
                if request.source_component_id != owner.component_id:
                    raise AssociationExistsError(
                        "the member belongs to another component; name it as the source"
                    )
                if request.source_expected_version is None:
                    raise ProjectInputError("source_expected_version is required")
                source = _require_component(
                    tx,
                    request.project_id,
                    owner.component_id,
                    request.source_expected_version,
                )
                kept = tuple(m for m in source.members if m != request.member)
                if kept:
                    tx.components.update(
                        replace(source, members=kept, reason=COMPONENT_REASON_OPERATOR),
                        expected_version=source.version,
                    )
                else:
                    tx.components.delete(
                        request.project_id,
                        source.component_id,
                        expected_version=source.version,
                    )
            return tx.components.update(
                replace(
                    target,
                    members=(*target.members, request.member),
                    reason=COMPONENT_REASON_OPERATOR,
                ),
                expected_version=target.version,
            )


@dataclass(frozen=True, slots=True)
class SplitComponentRequest:
    project_id: str
    component_id: str
    expected_version: int
    scope: SourceScope
    new_prefix: str
    name: str


class SplitComponent:
    """Carve a directory out of a component member into a new component."""

    def __init__(
        self,
        *,
        store: ProjectUnitOfWork,
        new_component_id: Callable[[], str] = new_component_id,
    ) -> None:
        self._store = store
        self._new_id = new_component_id

    def execute(self, request: SplitComponentRequest) -> ProjectComponent:
        """Raises:
        ProjectNotFoundError, ComponentNotFoundError, ProjectInputError,
        AssociationExistsError, ProjectRecordVersionConflictError.
        """
        new_prefix = normalize_path_prefix(request.new_prefix)
        if new_prefix == "":
            raise ProjectInputError("a split needs a non-empty path prefix")
        with self._store.transaction() as tx:
            require_project(tx, request.project_id)
            base = _require_component(
                tx, request.project_id, request.component_id, request.expected_version
            )
            covered = any(
                member.scope == request.scope
                and member.path_prefix != new_prefix
                and prefix_matches(member.path_prefix, new_prefix)
                for member in base.members
            )
            if not covered:
                raise ProjectInputError(
                    "the prefix must lie under a member prefix of this component"
                )
            member = ComponentMember(request.scope, new_prefix)
            if _owner_of(tx, request.project_id, member) is not None:
                raise AssociationExistsError("the project already has this member")
            tx.components.update(
                replace(base, reason=COMPONENT_REASON_OPERATOR),
                expected_version=base.version,
            )
            created = ProjectComponent(
                component_id=self._new_id(),
                project_id=request.project_id,
                name=request.name,
                members=(member,),
                reason=COMPONENT_REASON_OPERATOR,
                version=1,
            )
            tx.components.add(created)
        return created


@dataclass(frozen=True, slots=True)
class MergeComponentsRequest:
    project_id: str
    components: tuple[tuple[str, int], ...]
    name: str


class MergeComponents:
    """Merge components into the first one; the others are deleted."""

    def __init__(self, *, store: ProjectUnitOfWork) -> None:
        self._store = store

    def execute(self, request: MergeComponentsRequest) -> ProjectComponent:
        """Raises:
        ProjectNotFoundError, ComponentNotFoundError, ProjectInputError,
        ProjectRecordVersionConflictError.
        """
        ids = [component_id for component_id, _ in request.components]
        if len(ids) < 2 or len(set(ids)) != len(ids):
            raise ProjectInputError("merge needs at least two distinct components")
        with self._store.transaction() as tx:
            require_project(tx, request.project_id)
            merged = [
                _require_component(tx, request.project_id, component_id, version)
                for component_id, version in request.components
            ]
            survivor, others = merged[0], merged[1:]
            for other in others:
                tx.components.delete(
                    request.project_id,
                    other.component_id,
                    expected_version=other.version,
                )
            members = tuple(m for component in merged for m in component.members)
            return tx.components.update(
                replace(
                    survivor,
                    name=request.name,
                    members=members,
                    reason=COMPONENT_REASON_OPERATOR,
                ),
                expected_version=survivor.version,
            )


def _resolve_in_project(
    members: list[tuple[ComponentMember, str]], path: str | None
) -> tuple[ComponentResolutionStatus, tuple[str, ...]]:
    if path is not None and not is_valid_path(path):
        return ComponentResolutionStatus.INVALID_PATH, ()
    matches = [
        (prefix_depth(member.path_prefix), component_id)
        for member, component_id in members
        if (
            member.path_prefix == ""
            if path is None
            else prefix_matches(member.path_prefix, path)
        )
    ]
    if not matches:
        return ComponentResolutionStatus.UNASSIGNED, ()
    deepest = max(depth for depth, _ in matches)
    winners = tuple(sorted({cid for depth, cid in matches if depth == deepest}))
    if len(winners) > 1:
        return ComponentResolutionStatus.AMBIGUOUS, winners
    return ComponentResolutionStatus.RESOLVED, winners


class ResolveComponentsForSource:
    """Resolve a document to at most one component in each associated project."""

    def __init__(
        self,
        *,
        store: ProjectUnitOfWork,
        catalog: DocumentCatalog,
        resolvers: Mapping[str, SourceScopeResolver],
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._resolvers = resolvers

    def execute(self, reference: SourceReference) -> tuple[ComponentResolution, ...]:
        """Return one resolution per project with a confirmed association."""
        document = self._catalog.get(reference)
        if document is None:
            return ()
        scopes = document_scopes(document, self._resolvers)
        if not scopes:
            return ()
        path = self._resolvers[str(document.reference.source_type)].path_for(document)
        with self._store.read() as tx:
            projects = sorted(
                {
                    association.project_id
                    for scope in scopes
                    for association in tx.associations.for_scope(scope)
                    if association.state is AssociationState.CONFIRMED
                }
            )
            resolutions = []
            for project_id in projects:
                members = [
                    (member, component.component_id)
                    for component in tx.components.for_project(project_id)
                    for member in component.members
                    if member.scope in scopes
                    and _confirmed(tx, project_id, member.scope)
                ]
                status, component_ids = _resolve_in_project(members, path)
                resolutions.append(
                    ComponentResolution(project_id, status, component_ids)
                )
        return tuple(resolutions)


def _confirmed(tx: ProjectTransaction, project_id: str, scope: SourceScope) -> bool:
    association = tx.associations.get(project_id, scope)
    return association is not None and association.state is AssociationState.CONFIRMED
