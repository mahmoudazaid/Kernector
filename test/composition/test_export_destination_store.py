"""Tests for per-conversation Google Drive export destination persistence."""

from __future__ import annotations

from pathlib import Path

from composition.export_destination_store import (
    EXPORT_DESTINATION_NAMESPACE,
    VersionedExportDestinationRepository,
)
from infrastructure.workspace_store.sql_store import VersionedWorkspaceStore


def test_namespace_constant_is_locked() -> None:
    assert EXPORT_DESTINATION_NAMESPACE == "software-delivery:export-destination"


def test_upsert_then_get_round_trips_destination(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    repo = VersionedExportDestinationRepository(store)

    saved = repo.upsert(
        "conv-1", folder_id="folder-abc", display_label="QA / Sprint 3"
    )
    loaded = repo.get("conv-1")

    assert saved.folder_id == "folder-abc"
    assert saved.display_label == "QA / Sprint 3"
    assert loaded == saved


def test_upsert_replaces_existing_destination(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    repo = VersionedExportDestinationRepository(store)
    repo.upsert("conv-1", folder_id="folder-a", display_label="A")
    updated = repo.upsert("conv-1", folder_id="folder-b", display_label="B")

    assert updated.folder_id == "folder-b"
    assert updated.display_label == "B"
    assert updated.version >= 2
    assert repo.get("conv-1") == updated


def test_get_missing_returns_none(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    repo = VersionedExportDestinationRepository(store)
    assert repo.get("missing") is None


def test_workspaces_are_isolated(tmp_path: Path) -> None:
    path = tmp_path / "store.sqlite"
    a = VersionedExportDestinationRepository(VersionedWorkspaceStore(path, "ws-a"))
    b = VersionedExportDestinationRepository(VersionedWorkspaceStore(path, "ws-b"))
    a.upsert("conv-1", folder_id="folder-a", display_label="A")

    assert b.get("conv-1") is None
