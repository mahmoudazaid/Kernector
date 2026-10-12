"""SQLite project store: CAS, uniqueness, isolation and rollback (#372)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

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
from infrastructure.project.sql_store import SqlProjectStore

ORDERS = SourceScope("gh-1", "repo", "acme/oie-orders")
WEB = SourceScope("gh-1", "repo", "acme/oie-web")
OIE = Project("prj_oie", "Order Intake", "oie", 1)
PAY = Project("prj_pay", "Payments", "pay", 1)


def _association(
    project_id: str = "prj_oie",
    scope: SourceScope = ORDERS,
    state: AssociationState = AssociationState.CONFIRMED,
) -> SourceAssociation:
    return SourceAssociation(
        project_id=project_id,
        scope=scope,
        roles=("backend", "api_contract"),
        state=state,
        evidence=(SourceReference("site/OIE:OIE-1", "jira"),),
        created_by="operator",
        version=1,
    )


def _component(
    component_id: str = "cmp_orders",
    project_id: str = "prj_oie",
    members: tuple[ComponentMember, ...] = (ComponentMember(ORDERS),),
) -> ProjectComponent:
    return ProjectComponent(
        component_id, project_id, "oie-orders", members, "association_default", 1
    )


@pytest.fixture
def store(tmp_path: Path) -> SqlProjectStore:
    return SqlProjectStore(tmp_path / "catalog.sqlite", "ws-a")


def _seed(store: SqlProjectStore, *projects: Project) -> None:
    with store.transaction() as tx:
        for project in projects:
            tx.projects.add(project)


def test_projects_are_created_listed_and_fetched(store: SqlProjectStore) -> None:
    _seed(store, OIE, PAY)

    with store.read() as tx:
        assert tx.projects.get("prj_oie") == OIE
        assert tx.projects.get("prj_missing") is None
        assert {p.project_id for p in tx.projects.list()} == {"prj_oie", "prj_pay"}


def test_slug_is_unique_within_a_workspace(store: SqlProjectStore) -> None:
    _seed(store, OIE)

    with pytest.raises(ProjectSlugTakenError):
        _seed(store, Project("prj_other", "Other", "oie", 1))


def test_projects_are_isolated_per_workspace(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    _seed(SqlProjectStore(path, "ws-a"), OIE)
    other = SqlProjectStore(path, "ws-b")
    _seed(other, Project("prj_b", "Same slug", "oie", 1))

    with other.read() as tx:
        assert tx.projects.get("prj_oie") is None
        assert [p.project_id for p in tx.projects.list()] == ["prj_b"]


@pytest.mark.parametrize("workspace_id", ["", "bad id", "x" * 65])
def test_invalid_workspace_is_rejected_before_touching_disk(
    tmp_path: Path, workspace_id: str
) -> None:
    path = tmp_path / "nested" / "catalog.sqlite"

    with pytest.raises(ValueError, match="workspace_id"):
        SqlProjectStore(path, workspace_id)
    assert not path.parent.exists()


def test_association_round_trips_with_roles_and_evidence(
    store: SqlProjectStore,
) -> None:
    _seed(store, OIE)
    with store.transaction() as tx:
        tx.associations.add(_association())

    with store.read() as tx:
        assert tx.associations.get("prj_oie", ORDERS) == _association()
        assert tx.associations.get("prj_oie", WEB) is None
        assert tx.associations.for_project("prj_oie") == (_association(),)


def test_duplicate_association_is_rejected(store: SqlProjectStore) -> None:
    _seed(store, OIE)
    with store.transaction() as tx:
        tx.associations.add(_association())

    with pytest.raises(AssociationExistsError), store.transaction() as tx:
        tx.associations.add(_association(state=AssociationState.SUGGESTED))


def test_for_scope_lists_every_project(store: SqlProjectStore) -> None:
    _seed(store, OIE, PAY)
    with store.transaction() as tx:
        tx.associations.add(_association("prj_oie"))
        tx.associations.add(_association("prj_pay", state=AssociationState.SUGGESTED))
        tx.associations.add(_association("prj_pay", scope=WEB))

    with store.read() as tx:
        found = {(a.project_id, a.state) for a in tx.associations.for_scope(ORDERS)}

    assert found == {
        ("prj_oie", AssociationState.CONFIRMED),
        ("prj_pay", AssociationState.SUGGESTED),
    }


def test_association_update_uses_compare_and_swap(store: SqlProjectStore) -> None:
    _seed(store, OIE)
    suggested = _association(state=AssociationState.SUGGESTED)
    with store.transaction() as tx:
        tx.associations.add(suggested)

    confirmed = replace(suggested, state=AssociationState.CONFIRMED)
    with store.transaction() as tx:
        stored = tx.associations.update(confirmed, expected_version=1)

    assert stored.version == 2
    with pytest.raises(ProjectRecordVersionConflictError), store.transaction() as tx:
        tx.associations.update(confirmed, expected_version=1)
    with pytest.raises(AssociationNotFoundError), store.transaction() as tx:
        tx.associations.update(replace(confirmed, scope=WEB), expected_version=1)


def test_association_delete_uses_compare_and_swap(store: SqlProjectStore) -> None:
    _seed(store, OIE)
    with store.transaction() as tx:
        tx.associations.add(_association())

    with pytest.raises(ProjectRecordVersionConflictError), store.transaction() as tx:
        tx.associations.delete("prj_oie", ORDERS, expected_version=7)
    with store.transaction() as tx:
        tx.associations.delete("prj_oie", ORDERS, expected_version=1)

    with store.read() as tx:
        assert tx.associations.get("prj_oie", ORDERS) is None
    with pytest.raises(AssociationNotFoundError), store.transaction() as tx:
        tx.associations.delete("prj_oie", ORDERS, expected_version=1)


def test_component_round_trips_and_updates_with_cas(store: SqlProjectStore) -> None:
    _seed(store, OIE)
    members = (ComponentMember(ORDERS), ComponentMember(WEB, "web"))
    with store.transaction() as tx:
        tx.components.add(_component(members=members))

    with store.read() as tx:
        assert tx.components.get("prj_oie", "cmp_orders") == _component(members=members)
        assert tx.components.get("prj_pay", "cmp_orders") is None

    renamed = replace(_component(), name="orders", reason="operator")
    with store.transaction() as tx:
        stored = tx.components.update(renamed, expected_version=1)
    assert stored.version == 2
    assert stored.members == (ComponentMember(ORDERS),)

    with pytest.raises(ProjectRecordVersionConflictError), store.transaction() as tx:
        tx.components.update(renamed, expected_version=1)
    with pytest.raises(ComponentNotFoundError), store.transaction() as tx:
        tx.components.update(replace(renamed, component_id="cmp_x"), expected_version=1)


def test_member_is_unique_within_a_project(store: SqlProjectStore) -> None:
    _seed(store, OIE, PAY)
    with store.transaction() as tx:
        tx.components.add(_component())
        tx.components.add(_component("cmp_pay", "prj_pay"))

    with pytest.raises(AssociationExistsError), store.transaction() as tx:
        tx.components.add(_component("cmp_dup"))


def test_component_delete_uses_compare_and_swap(store: SqlProjectStore) -> None:
    _seed(store, OIE)
    with store.transaction() as tx:
        tx.components.add(_component())

    with pytest.raises(ProjectRecordVersionConflictError), store.transaction() as tx:
        tx.components.delete("prj_oie", "cmp_orders", expected_version=2)
    with store.transaction() as tx:
        tx.components.delete("prj_oie", "cmp_orders", expected_version=1)

    with store.read() as tx:
        assert tx.components.for_project("prj_oie") == ()
    with store.transaction() as tx:
        tx.components.add(_component("cmp_again"))


def test_failure_inside_a_transaction_rolls_back_every_record(
    store: SqlProjectStore,
) -> None:
    _seed(store, OIE)

    with pytest.raises(RuntimeError, match="boom"), store.transaction() as tx:
        tx.projects.add(PAY)
        tx.associations.add(_association())
        tx.components.add(_component())
        raise RuntimeError("boom")

    with store.read() as tx:
        assert tx.projects.get("prj_pay") is None
        assert tx.associations.for_project("prj_oie") == ()
        assert tx.components.for_project("prj_oie") == ()


def test_components_are_isolated_per_workspace(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    first = SqlProjectStore(path, "ws-a")
    _seed(first, OIE)
    with first.transaction() as tx:
        tx.associations.add(_association())
        tx.components.add(_component())

    with SqlProjectStore(path, "ws-b").read() as tx:
        assert tx.components.for_project("prj_oie") == ()
        assert tx.associations.for_scope(ORDERS) == ()
