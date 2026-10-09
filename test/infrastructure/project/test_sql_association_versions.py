"""Association versions are never reused for the same key (#372, ABA)."""

from __future__ import annotations

from pathlib import Path

import pytest

from application.project.associations import (
    AssociateSource,
    AssociateSourceRequest,
    RemoveAssociation,
    RemoveAssociationRequest,
)
from application.project.suggest import SuggestAssociations
from domain.knowledge import SourceReference
from domain.project.errors import ProjectRecordVersionConflictError
from domain.project.models import (
    AssociationEvidence,
    AssociationState,
    ComponentMember,
    Project,
    SourceScope,
)
from infrastructure.project.sql_store import SqlProjectStore
from test.application.project.project_fakes import confirmed

ORDERS = SourceScope("gh-1", "repo", "acme/oie-orders")
OIE_JIRA = SourceScope("jira-1", "project_key", "OIE")


def _open(path: Path, workspace_id: str = "ws") -> SqlProjectStore:
    return SqlProjectStore(path, workspace_id)


def _seed(store: SqlProjectStore) -> None:
    with store.transaction() as tx:
        tx.projects.add(Project("prj_oie", "Order Intake", "oie", 1))


def _associate(store: SqlProjectStore) -> int:
    return (
        AssociateSource(store=store, component_forming_kinds=frozenset({"repo"}))
        .execute(AssociateSourceRequest("prj_oie", ORDERS, (), "operator"))
        .version
    )


def _remove(store: SqlProjectStore, version: int) -> None:
    RemoveAssociation(store=store).execute(
        RemoveAssociationRequest("prj_oie", ORDERS, expected_version=version)
    )


def _snapshot(store: SqlProjectStore):
    with store.read() as tx:
        return (
            tx.associations.get("prj_oie", ORDERS),
            tx.components.for_project("prj_oie"),
        )


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "catalog.sqlite"


def test_replayed_delete_after_recreate_is_a_version_conflict(path: Path) -> None:
    store = _open(path)
    _seed(store)
    assert _associate(store) == 1
    _remove(store, 1)
    recreated_version = _associate(store)
    before = _snapshot(store)

    with pytest.raises(ProjectRecordVersionConflictError):
        _remove(store, 1)

    assert recreated_version > 1
    assert _snapshot(store) == before
    association, (component,) = before
    assert association is not None
    assert association.version == recreated_version
    assert component.members == (ComponentMember(ORDERS, ""),)


def test_versions_stay_unique_across_store_reopening(path: Path) -> None:
    store = _open(path)
    _seed(store)
    _remove(store, _associate(store))
    second = _associate(store)

    reopened = _open(path)
    with pytest.raises(ProjectRecordVersionConflictError):
        _remove(reopened, 1)
    _remove(reopened, second)
    third = _associate(_open(path))

    assert 1 < second < third
    with pytest.raises(ProjectRecordVersionConflictError):
        _remove(_open(path), second)


def test_removed_association_is_excluded_immediately(path: Path) -> None:
    store = _open(path)
    _seed(store)
    _remove(store, _associate(store))

    with store.read() as tx:
        assert tx.associations.for_scope(ORDERS) == ()
        assert tx.associations.get("prj_oie", ORDERS) is None
        assert tx.components.for_project("prj_oie") == ()


def test_version_history_is_isolated_per_workspace(path: Path) -> None:
    first = _open(path, "ws-a")
    _seed(first)
    _remove(first, _associate(first))
    assert _associate(first) > 1

    other = _open(path, "ws-b")
    _seed(other)

    assert _associate(other) == 1


class _Evidence:
    def evidence(self) -> tuple[AssociationEvidence, ...]:
        reference = SourceReference("cloud-abc/OIE:OIE-123", "jira")
        return (AssociationEvidence(OIE_JIRA, ORDERS, reference, "remotelinks"),)


def test_suggestion_after_removal_returns_the_stored_version(path: Path) -> None:
    store = _open(path)
    _seed(store)
    with store.transaction() as tx:
        tx.associations.add(confirmed("prj_oie", OIE_JIRA))
    _remove(store, _associate(store))

    (suggestion,) = SuggestAssociations(store=store, evidence=_Evidence()).execute()

    assert suggestion.state is AssociationState.SUGGESTED
    assert suggestion.version > 1
    stored, _ = _snapshot(store)
    assert stored == suggestion
