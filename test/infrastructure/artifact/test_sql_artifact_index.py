"""SQLite ArtifactIndex: upsert, remove, find_by_key, workspace isolation (#373)."""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor, ContextAssignment
from domain.knowledge import SourceReference
from infrastructure.artifact.sql_index import SqlArtifactIndex


def _descriptor(
    source_id: str = "cloud/PROJ:PROJ-123",
    *,
    kind: str = ArtifactKind.STORY,
    keys: tuple[str, ...] = ("PROJ-123",),
    revision: str = "r1",
) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        reference=SourceReference(source_id, "jira"),
        revision=revision,
        kind=kind,
        contexts=(ContextAssignment("business", "role_default"),),
        component_ids=("cmp_jira",),
        external_keys=keys,
        title=f"{source_id} title",
        url="https://example.test/browse/PROJ-123",
    )


@pytest.fixture
def index(tmp_path: Path) -> SqlArtifactIndex:
    return SqlArtifactIndex(tmp_path / "catalog.sqlite", "ws-a")


def test_upsert_get_and_find_by_key(index: SqlArtifactIndex) -> None:
    descriptor = _descriptor()

    index.upsert(descriptor)

    assert index.get(descriptor.reference) == descriptor
    assert index.find_by_key(("PROJ-123",)) == (descriptor,)
    assert index.find_by_key(("PAY-123",)) == ()


def test_upsert_replaces_descriptor_and_keys(index: SqlArtifactIndex) -> None:
    index.upsert(_descriptor(revision="r1", keys=("PROJ-123",)))
    updated = _descriptor(revision="r2", keys=("PROJ-123", "cancelOrder"))

    index.upsert(updated)

    assert index.get(updated.reference) == updated
    assert index.find_by_key(("cancelOrder",)) == (updated,)


def test_remove_deletes_descriptor_and_keys(index: SqlArtifactIndex) -> None:
    descriptor = _descriptor()
    index.upsert(descriptor)

    index.remove(descriptor.reference)

    assert index.get(descriptor.reference) is None
    assert index.find_by_key(("PROJ-123",)) == ()


def test_workspace_isolation(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    a = SqlArtifactIndex(path, "ws-a")
    b = SqlArtifactIndex(path, "ws-b")
    descriptor = _descriptor()

    a.upsert(descriptor)

    assert a.find_by_key(("PROJ-123",)) == (descriptor,)
    assert b.find_by_key(("PROJ-123",)) == ()
    assert b.get(descriptor.reference) is None


def test_list_for_scope_filters_source_type(index: SqlArtifactIndex) -> None:
    jira = _descriptor()
    github = ArtifactDescriptor(
        reference=SourceReference("acme/proj:orders/cancel.py", "github"),
        revision="sha",
        kind=ArtifactKind.CODE_FILE,
    )
    index.upsert(jira)
    index.upsert(github)

    assert index.list_for_scope(source_type="jira") == (jira,)
    assert {d.reference.source_id for d in index.list_for_scope()} == {
        jira.reference.source_id,
        github.reference.source_id,
    }
