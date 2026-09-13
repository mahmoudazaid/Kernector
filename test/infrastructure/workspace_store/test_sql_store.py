"""Tests for the namespaced versioned workspace store."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from infrastructure.workspace_store.errors import (
    VersionedStoreConflictError,
    VersionedStoreNotFoundError,
    VersionedStoreVersionConflictError,
)
from infrastructure.workspace_store.sql_store import VersionedWorkspaceStore


def test_create_returns_version_one(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    record = store.create("software-delivery:test-design", "draft-1", '{"v":1}')

    assert record.workspace_id == "ws-a"
    assert record.namespace == "software-delivery:test-design"
    assert record.record_id == "draft-1"
    assert record.payload == '{"v":1}'
    assert record.version == 1
    assert record.created_at.tzinfo is UTC
    assert record.updated_at == record.created_at


def test_create_fails_when_key_exists(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    store.create("ns", "r1", "{}")
    with pytest.raises(VersionedStoreConflictError, match="already exists"):
        store.create("ns", "r1", '{"other":true}')


def test_get_returns_persisted_record(tmp_path: Path) -> None:
    path = tmp_path / "store.sqlite"
    VersionedWorkspaceStore(path, "ws-a").create("ns", "r1", '{"a":1}')
    record = VersionedWorkspaceStore(path, "ws-a").get("ns", "r1")

    assert record is not None
    assert record.payload == '{"a":1}'
    assert record.version == 1


def test_get_missing_returns_none(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    assert store.get("ns", "missing") is None


def test_get_is_scoped_by_workspace_and_namespace(tmp_path: Path) -> None:
    path = tmp_path / "store.sqlite"
    VersionedWorkspaceStore(path, "ws-a").create("ns-a", "r1", '{"ws":"a"}')
    VersionedWorkspaceStore(path, "ws-b").create("ns-a", "r1", '{"ws":"b"}')
    VersionedWorkspaceStore(path, "ws-a").create("ns-b", "r1", '{"ns":"b"}')

    assert VersionedWorkspaceStore(path, "ws-a").get("ns-a", "r1").payload == '{"ws":"a"}'
    assert VersionedWorkspaceStore(path, "ws-b").get("ns-a", "r1").payload == '{"ws":"b"}'
    assert VersionedWorkspaceStore(path, "ws-a").get("ns-b", "r1").payload == '{"ns":"b"}'
    assert VersionedWorkspaceStore(path, "ws-a").get("ns-a", "missing") is None


def test_update_increments_version_on_cas_success(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    created = store.create("ns", "r1", '{"n":1}')
    updated = store.update("ns", "r1", '{"n":2}', expected_version=created.version)

    assert updated.version == 2
    assert updated.payload == '{"n":2}'
    assert updated.created_at == created.created_at
    assert updated.updated_at >= created.updated_at


def test_update_version_conflict_when_expected_stale(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    store.create("ns", "r1", '{"n":1}')
    store.update("ns", "r1", '{"n":2}', expected_version=1)

    with pytest.raises(VersionedStoreVersionConflictError, match="version"):
        store.update("ns", "r1", '{"n":3}', expected_version=1)

    assert store.get("ns", "r1").payload == '{"n":2}'
    assert store.get("ns", "r1").version == 2


def test_update_not_found_for_unknown_record(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    with pytest.raises(VersionedStoreNotFoundError, match="not found"):
        store.update("ns", "missing", "{}", expected_version=1)


def test_timestamps_are_server_authored_utc(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    before = datetime.now(UTC)
    record = store.create("ns", "r1", "{}")
    after = datetime.now(UTC)

    assert before <= record.created_at <= after
    assert record.created_at.tzinfo is UTC


@pytest.mark.parametrize("workspace_id", ["bad id", "ws/id", "", "   "])
def test_constructor_rejects_invalid_workspace_id(
    tmp_path: Path, workspace_id: str
) -> None:
    path = tmp_path / "nested" / "store.sqlite"
    with pytest.raises(ValueError, match="workspace_id"):
        VersionedWorkspaceStore(path, workspace_id)
    assert not path.exists()
