"""SubmitResponseFeedback / ClearResponseFeedback use cases (#219)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from application.errors import InputRejectedError
from application.submit_response_feedback import (
    ClearFeedbackRequest,
    ClearResponseFeedback,
    FeedbackNotFoundError,
    NullRunProvenanceLookup,
    SubmitResponseFeedback,
    UpsertFeedbackRequest,
)
from domain.response_feedback import ResponseFeedback, RunProvenance


@dataclass
class _FakeRepository:
    workspace_id: str = "ws-a"
    rows: dict[str, ResponseFeedback] = field(default_factory=dict)

    def upsert(self, feedback: ResponseFeedback) -> ResponseFeedback:
        existing = self.rows.get(feedback.request_id)
        if existing is not None:
            feedback = ResponseFeedback(
                workspace_id=feedback.workspace_id,
                request_id=feedback.request_id,
                rating=feedback.rating,
                created_at=existing.created_at,
                updated_at=feedback.updated_at,
                conversation_id=feedback.conversation_id,
                client_message_id=feedback.client_message_id,
                run_id=feedback.run_id,
                reason=feedback.reason,
                comment=feedback.comment,
                prompt_key=feedback.prompt_key,
                prompt_version=feedback.prompt_version,
                model=feedback.model,
                tools=feedback.tools,
            )
        self.rows[feedback.request_id] = feedback
        return feedback

    def get(self, request_id: str) -> ResponseFeedback | None:
        return self.rows.get(request_id)

    def delete(self, request_id: str) -> bool:
        return self.rows.pop(request_id, None) is not None


@dataclass
class _FakeProvenance:
    by_id: dict[str, RunProvenance] = field(default_factory=dict)

    def get(self, request_id: str) -> RunProvenance | None:
        return self.by_id.get(request_id)


def test_submit_positive_rating_without_provenance_leaves_prompt_null() -> None:
    repo = _FakeRepository()
    use_case = SubmitResponseFeedback(
        repository=repo,
        provenance=NullRunProvenanceLookup(),
        workspace_id="ws-a",
    )
    stored = use_case.execute(
        UpsertFeedbackRequest(
            request_id="req-1",
            rating="positive",
            conversation_id="conv-1",
            client_message_id="a-1",
        )
    )
    assert stored.workspace_id == "ws-a"
    assert stored.request_id == "req-1"
    assert stored.rating == "positive"
    assert stored.conversation_id == "conv-1"
    assert stored.client_message_id == "a-1"
    assert stored.prompt_key is None
    assert stored.prompt_version is None
    assert stored.model is None
    assert stored.tools == ()
    assert repo.get("req-1") == stored


def test_submit_merges_trusted_provenance_and_ignores_client_prompt_fields() -> None:
    repo = _FakeRepository()
    provenance = _FakeProvenance(
        by_id={
            "req-2": RunProvenance(
                request_id="req-2",
                conversation_id="conv-trusted",
                run_id="run-9",
                prompt_key="software-delivery.agent",
                prompt_version="v1",
                model="gpt-test",
                tools=("search", "export"),
            )
        }
    )
    use_case = SubmitResponseFeedback(
        repository=repo,
        provenance=provenance,
        workspace_id="ws-a",
    )
    stored = use_case.execute(
        UpsertFeedbackRequest(
            request_id="req-2",
            rating="negative",
            reason="wrong_tool",
            conversation_id="conv-client",
        )
    )
    assert stored.conversation_id == "conv-trusted"
    assert stored.run_id == "run-9"
    assert stored.prompt_key == "software-delivery.agent"
    assert stored.prompt_version == "v1"
    assert stored.model == "gpt-test"
    assert stored.tools == ("search", "export")
    assert stored.reason == "wrong_tool"


def test_submit_rejects_reason_on_positive_rating() -> None:
    use_case = SubmitResponseFeedback(
        repository=_FakeRepository(),
        workspace_id="ws-a",
    )
    with pytest.raises(InputRejectedError, match="reason"):
        use_case.execute(
            UpsertFeedbackRequest(
                request_id="req-1",
                rating="positive",
                reason="incorrect",
            )
        )


def test_submit_rejects_unknown_reason() -> None:
    use_case = SubmitResponseFeedback(
        repository=_FakeRepository(),
        workspace_id="ws-a",
    )
    with pytest.raises(InputRejectedError, match="reason"):
        use_case.execute(
            UpsertFeedbackRequest(
                request_id="req-1",
                rating="negative",
                reason="not-a-reason",  # type: ignore[arg-type]
            )
        )


def test_submit_rejects_blank_request_id() -> None:
    use_case = SubmitResponseFeedback(
        repository=_FakeRepository(),
        workspace_id="ws-a",
    )
    with pytest.raises(InputRejectedError, match="request_id"):
        use_case.execute(UpsertFeedbackRequest(request_id="  ", rating="positive"))


def test_clear_deletes_existing_rating() -> None:
    repo = _FakeRepository()
    submit = SubmitResponseFeedback(repository=repo, workspace_id="ws-a")
    submit.execute(UpsertFeedbackRequest(request_id="req-1", rating="positive"))
    ClearResponseFeedback(repository=repo).execute(
        ClearFeedbackRequest(request_id="req-1")
    )
    assert repo.get("req-1") is None


def test_clear_missing_raises_not_found() -> None:
    repo = _FakeRepository()
    with pytest.raises(FeedbackNotFoundError):
        ClearResponseFeedback(repository=repo).execute(
            ClearFeedbackRequest(request_id="req-missing")
        )
