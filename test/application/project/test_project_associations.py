"""Create projects and manage source associations (#372)."""

from __future__ import annotations

import pytest

from application.project.associations import (
    AssociateSource,
    AssociateSourceRequest,
    ConfirmAssociation,
    ConfirmAssociationRequest,
    RemoveAssociation,
    RemoveAssociationRequest,
)
from application.project.projects import CreateProject, CreateProjectRequest
from domain.project.errors import (
    AssociationExistsError,
    ProjectNotFoundError,
    ProjectRecordVersionConflictError,
    ProjectSlugTakenError,
    SharedScopeConfirmationRequiredError,
)
from domain.project.models import AssociationState, SourceAssociation, SourceScope
from test.application.project.project_fakes import InMemoryProjectStore

LIB = SourceScope("gh-1", "repo", "acme/shared-lib")
ORDERS = SourceScope("gh-1", "repo", "acme/oie-orders")


@pytest.fixture
def store() -> InMemoryProjectStore:
    return InMemoryProjectStore()


def _create(store: InMemoryProjectStore, slug: str) -> str:
    return CreateProject(store=store).execute(CreateProjectRequest(slug.upper(), slug)).project_id


def _associate(
    store: InMemoryProjectStore,
    project_id: str,
    scope: SourceScope = LIB,
    acknowledged: frozenset[str] = frozenset(),
) -> SourceAssociation:
    return AssociateSource(store=store).execute(
        AssociateSourceRequest(
            project_id=project_id,
            scope=scope,
            roles=(),
            created_by="operator",
            acknowledged_shared_with=acknowledged,
        )
    )


def test_create_project_generates_an_opaque_id(store: InMemoryProjectStore) -> None:
    project = CreateProject(store=store).execute(CreateProjectRequest("Order Intake", "oie"))

    assert project.project_id.startswith("prj_")
    assert project.project_id != "oie"
    assert project.version == 1
    with store.read() as tx:
        assert tx.projects.get(project.project_id) == project


def test_slug_collision_is_reported(store: InMemoryProjectStore) -> None:
    _create(store, "oie")

    with pytest.raises(ProjectSlugTakenError):
        _create(store, "oie")


def test_associate_requires_an_existing_project(store: InMemoryProjectStore) -> None:
    with pytest.raises(ProjectNotFoundError):
        _associate(store, "prj_missing")


def test_explicit_association_is_confirmed(store: InMemoryProjectStore) -> None:
    oie = _create(store, "oie")

    association = _associate(store, oie)

    assert association.state is AssociationState.CONFIRMED
    assert association.version == 1


def test_associating_the_same_scope_twice_is_rejected(
    store: InMemoryProjectStore,
) -> None:
    oie = _create(store, "oie")
    _associate(store, oie)

    with pytest.raises(AssociationExistsError):
        _associate(store, oie)


def test_shared_scope_needs_named_acknowledgement(store: InMemoryProjectStore) -> None:
    oie, pay = _create(store, "oie"), _create(store, "pay")
    _associate(store, oie)

    with pytest.raises(SharedScopeConfirmationRequiredError) as raised:
        _associate(store, pay)

    assert raised.value.project_ids == (oie,)
    with store.read() as tx:
        assert tx.associations.get(pay, LIB) is None
    assert _associate(store, pay, acknowledged=frozenset({oie})).project_id == pay


def test_stale_acknowledgement_does_not_cover_a_new_project(
    store: InMemoryProjectStore,
) -> None:
    oie, pay, ops = _create(store, "oie"), _create(store, "pay"), _create(store, "ops")
    _associate(store, oie)
    _associate(store, pay, acknowledged=frozenset({oie}))

    with pytest.raises(SharedScopeConfirmationRequiredError) as raised:
        _associate(store, ops, acknowledged=frozenset({oie}))

    assert raised.value.project_ids == tuple(sorted((oie, pay)))


def test_suggested_association_elsewhere_is_not_a_conflict(
    store: InMemoryProjectStore,
) -> None:
    oie, pay = _create(store, "oie"), _create(store, "pay")
    with store.transaction() as tx:
        tx.associations.add(
            SourceAssociation(oie, LIB, (), AssociationState.SUGGESTED, (), "pack", 1)
        )

    assert _associate(store, pay).state is AssociationState.CONFIRMED


def test_confirm_needs_the_current_version(store: InMemoryProjectStore) -> None:
    oie = _create(store, "oie")
    with store.transaction() as tx:
        tx.associations.add(
            SourceAssociation(oie, ORDERS, (), AssociationState.SUGGESTED, (), "pack", 1)
        )
    confirm = ConfirmAssociation(store=store)

    with pytest.raises(ProjectRecordVersionConflictError):
        confirm.execute(ConfirmAssociationRequest(oie, ORDERS, expected_version=3))
    confirmed = confirm.execute(ConfirmAssociationRequest(oie, ORDERS, expected_version=1))

    assert confirmed.state is AssociationState.CONFIRMED
    assert confirmed.version == 2


def test_remove_needs_the_current_version(store: InMemoryProjectStore) -> None:
    oie = _create(store, "oie")
    _associate(store, oie)
    remove = RemoveAssociation(store=store)

    with pytest.raises(ProjectRecordVersionConflictError):
        remove.execute(RemoveAssociationRequest(oie, LIB, expected_version=2))
    remove.execute(RemoveAssociationRequest(oie, LIB, expected_version=1))

    with store.read() as tx:
        assert tx.associations.get(oie, LIB) is None
