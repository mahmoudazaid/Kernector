"""Component use cases against the SQLite project store (#372)."""

from __future__ import annotations

from pathlib import Path

import pytest

from application.project.associations import (
    AssociateSource,
    AssociateSourceRequest,
    RemoveAssociation,
    RemoveAssociationRequest,
)
from application.project.components import (
    MergeComponents,
    MergeComponentsRequest,
    SplitComponent,
    SplitComponentRequest,
)
from domain.project.models import ComponentMember, Project, SourceScope
from infrastructure.project.sql_store import SqlProjectStore

MONO = SourceScope("gh-1", "repo", "acme/mono")
WEB = SourceScope("gh-1", "repo", "acme/oie-web")


@pytest.fixture
def store(tmp_path: Path) -> SqlProjectStore:
    store = SqlProjectStore(tmp_path / "catalog.sqlite", "ws")
    with store.transaction() as tx:
        tx.projects.add(Project("prj_oie", "Order Intake", "oie", 1))
    return store


def _associate(store: SqlProjectStore, scope: SourceScope) -> None:
    AssociateSource(store=store, component_forming_kinds=frozenset({"repo"})).execute(
        AssociateSourceRequest("prj_oie", scope, (), "operator")
    )


def test_split_merge_and_remove_round_trip(store: SqlProjectStore) -> None:
    _associate(store, MONO)
    _associate(store, WEB)
    with store.read() as tx:
        root, web = sorted(tx.components.for_project("prj_oie"), key=lambda c: c.name)
    split = SplitComponent(store=store).execute(
        SplitComponentRequest(
            "prj_oie", root.component_id, root.version, MONO, "web", "mono-web"
        )
    )
    merged = MergeComponents(store=store).execute(
        MergeComponentsRequest(
            "prj_oie",
            ((split.component_id, 1), (web.component_id, web.version)),
            "web",
        )
    )

    assert merged.members == (ComponentMember(MONO, "web"), ComponentMember(WEB, ""))
    RemoveAssociation(store=store).execute(
        RemoveAssociationRequest("prj_oie", MONO, expected_version=1)
    )
    with store.read() as tx:
        (remaining,) = tx.components.for_project("prj_oie")
    assert remaining.component_id == merged.component_id
    assert remaining.members == (ComponentMember(WEB, ""),)
