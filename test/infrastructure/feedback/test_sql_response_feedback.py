"""Tests for the SQLite response feedback repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.response_feedback import ResponseFeedback
from infrastructure.feedback.errors import FeedbackStoreError
from infrastructure.feedback.sql_repository import SqlResponseFeedbackRepository


def _feedback(
    *,
    workspace_id: str = "ws-a",
    request_id: str = "req-1",
    rating: str = "positive",
    created_at: str = "2026-09-17T10:00:00+00:00",
    updated_at: str = "2026-09-17T10:00:00+00:00",
    conversation_id: str | None = "conv-1",
    client_message_id: str | None = "a-1",
    reason: str | None = None,
    comment: str | None = None,
    prompt_key: str | None = None,
    prompt_version: str | None = None,
    model: str | None = None,
    tools: tuple[str, ...] = (),
) -> ResponseFeedback:
    return ResponseFeedback(
        workspace_id=workspace_id,
        request_id=request_id,
        rating=rating,  # type: ignore[arg-type]
        created_at=created_at,
        updated_at=updated_at,
        conversation_id=conversation_id,
        client_message_id=client_message_id,
        reason=reason,  # type: ignore[arg-type]
        comment=comment,
        prompt_key=prompt_key,
        prompt_version=prompt_version,
        model=model,
        tools=tools,
    )


def test_upsert_get_round_trip(tmp_path: Path) -> None:
    repo = SqlResponseFeedbackRepository(tmp_path / "feedback.sqlite", "ws-a")
    stored = repo.upsert(
        _feedback(
            rating="negative",
            reason="incorrect",
            comment="missed the cite",
            tools=("search",),
        )
    )
    assert stored.request_id == "req-1"
    assert stored.rating == "negative"
    assert stored.reason == "incorrect"
    assert stored.comment == "missed the cite"
    assert stored.tools == ("search",)
    assert repo.get("req-1") == stored


def test_upsert_is_idempotent_and_preserves_created_at(tmp_path: Path) -> None:
    path = tmp_path / "feedback.sqlite"
    repo = SqlResponseFeedbackRepository(path, "ws-a")
    first = repo.upsert(
        _feedback(rating="positive", updated_at="2026-09-17T10:00:00+00:00")
    )
    second = repo.upsert(
        _feedback(
            rating="negative",
            reason="incomplete",
            created_at="2026-09-17T11:00:00+00:00",
            updated_at="2026-09-17T11:00:00+00:00",
        )
    )
    assert second.rating == "negative"
    assert second.reason == "incomplete"
    assert second.created_at == first.created_at
    assert second.updated_at == "2026-09-17T11:00:00+00:00"
    assert repo.get("req-1") == second


def test_workspaces_isolate_the_same_request_id(tmp_path: Path) -> None:
    path = tmp_path / "feedback.sqlite"
    repo_a = SqlResponseFeedbackRepository(path, "ws-a")
    repo_b = SqlResponseFeedbackRepository(path, "ws-b")
    repo_a.upsert(_feedback(workspace_id="ws-a", rating="positive"))
    repo_b.upsert(
        _feedback(workspace_id="ws-b", rating="negative", reason="unclear")
    )
    assert repo_a.get("req-1") is not None
    assert repo_a.get("req-1").rating == "positive"  # type: ignore[union-attr]
    assert repo_b.get("req-1") is not None
    assert repo_b.get("req-1").rating == "negative"  # type: ignore[union-attr]


def test_delete_removes_record(tmp_path: Path) -> None:
    repo = SqlResponseFeedbackRepository(tmp_path / "feedback.sqlite", "ws-a")
    repo.upsert(_feedback())
    assert repo.delete("req-1") is True
    assert repo.get("req-1") is None


def test_delete_missing_returns_false(tmp_path: Path) -> None:
    repo = SqlResponseFeedbackRepository(tmp_path / "feedback.sqlite", "ws-a")
    assert repo.delete("req-missing") is False


def test_reopen_reads_persisted_records(tmp_path: Path) -> None:
    path = tmp_path / "feedback.sqlite"
    SqlResponseFeedbackRepository(path, "ws-a").upsert(_feedback())
    assert SqlResponseFeedbackRepository(path, "ws-a").get("req-1") is not None


def test_upsert_rejects_mismatched_workspace(tmp_path: Path) -> None:
    repo = SqlResponseFeedbackRepository(tmp_path / "feedback.sqlite", "ws-a")
    with pytest.raises(FeedbackStoreError):
        repo.upsert(_feedback(workspace_id="ws-other"))
