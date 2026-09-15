"""Tests for composition bridge over the versioned workspace store."""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.knowledge import SourceReference
from infrastructure.workspace_store.errors import (
    VersionedStoreConflictError,
    VersionedStoreNotFoundError,
    VersionedStoreVersionConflictError,
)
from infrastructure.workspace_store.sql_store import VersionedWorkspaceStore
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.models import (
    TestCandidate,
    TestCoverageDraft,
)
from composition.test_design_store import (
    TEST_DESIGN_NAMESPACE,
    VersionedTestCoverageDraftRepository,
)


def _ref() -> SourceReference:
    return SourceReference("PROJ-42", "jira")


def _draft(
    *,
    draft_id: str = "draft-1",
    workspace_id: str = "ws-a",
    version: int = 1,
    status: str = "coverage_review",
) -> TestCoverageDraft:
    return TestCoverageDraft(
        draft_id=draft_id,
        workspace_id=workspace_id,
        conversation_id="conv-1",
        source_reference=_ref(),
        ticket_identifier="KERN-293",
        status=status,  # type: ignore[arg-type]
        candidates=(
            TestCandidate(
                candidate_id="cand-1",
                title="Valid login",
                category="positive",
                rationale="AC covers login.",
                evidence_references=(_ref(),),
                selected=True,
                origin="suggested",
            ),
        ),
        version=version,
    )


def test_namespace_constant_is_locked() -> None:
    assert TEST_DESIGN_NAMESPACE == "software-delivery:test-design"


def test_create_get_round_trip(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    repo = VersionedTestCoverageDraftRepository(store)
    created = repo.create(_draft())

    assert created.version == 1
    assert repo.get("draft-1") == created


def test_create_conflict_when_draft_exists(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    repo = VersionedTestCoverageDraftRepository(store)
    repo.create(_draft())
    with pytest.raises(VersionedStoreConflictError):
        repo.create(_draft(version=1))


def test_update_cas_increments_version(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    repo = VersionedTestCoverageDraftRepository(store)
    created = repo.create(_draft())
    updated_input = _draft(status="ready", version=created.version)
    updated = repo.update(updated_input, expected_version=created.version)

    assert updated.version == 2
    assert updated.status == "ready"
    assert repo.get("draft-1") == updated


def test_update_version_conflict(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    repo = VersionedTestCoverageDraftRepository(store)
    repo.create(_draft())
    repo.update(_draft(status="ready", version=1), expected_version=1)
    with pytest.raises(VersionedStoreVersionConflictError):
        repo.update(_draft(status="ready", version=1), expected_version=1)


def test_update_not_found(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    repo = VersionedTestCoverageDraftRepository(store)
    with pytest.raises(VersionedStoreNotFoundError):
        repo.update(_draft(draft_id="missing"), expected_version=1)


def test_get_missing_returns_none(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    repo = VersionedTestCoverageDraftRepository(store)
    assert repo.get("missing") is None


def test_corrupt_payload_raises_validation_error(tmp_path: Path) -> None:
    store = VersionedWorkspaceStore(tmp_path / "store.sqlite", "ws-a")
    store.create(TEST_DESIGN_NAMESPACE, "draft-bad", "{not-json")
    repo = VersionedTestCoverageDraftRepository(store)
    with pytest.raises(TestDesignValidationError, match="payload"):
        repo.get("draft-bad")


def test_workspaces_isolate_drafts(tmp_path: Path) -> None:
    path = tmp_path / "store.sqlite"
    repo_a = VersionedTestCoverageDraftRepository(
        VersionedWorkspaceStore(path, "ws-a")
    )
    repo_b = VersionedTestCoverageDraftRepository(
        VersionedWorkspaceStore(path, "ws-b")
    )
    repo_a.create(_draft(workspace_id="ws-a"))
    repo_b.create(_draft(workspace_id="ws-b", draft_id="draft-1"))

    assert repo_a.get("draft-1") is not None
    assert repo_a.get("draft-1").workspace_id == "ws-a"
    assert repo_b.get("draft-1").workspace_id == "ws-b"
