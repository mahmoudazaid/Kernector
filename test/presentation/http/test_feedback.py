"""HTTP adapter tests for response feedback routes (#219)."""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from application.submit_response_feedback import (
    ClearFeedbackRequest,
    FeedbackNotFoundError,
    GetFeedbackRequest,
    UpsertFeedbackRequest,
)
from domain.response_feedback import ResponseFeedback
from presentation.http.app import create_app
from presentation.http.deps import (
    get_clear_response_feedback,
    get_get_response_feedback,
    get_submit_response_feedback,
)


@dataclass
class _StubSubmit:
    calls: list[UpsertFeedbackRequest] = field(default_factory=list)

    def execute(self, request: UpsertFeedbackRequest) -> ResponseFeedback:
        self.calls.append(request)
        return ResponseFeedback(
            workspace_id="ws-a",
            request_id=request.request_id,
            rating=request.rating,
            created_at="2026-09-17T10:00:00+00:00",
            updated_at="2026-09-17T10:00:00+00:00",
            conversation_id=request.conversation_id,
            client_message_id=request.client_message_id,
            reason=request.reason,
            comment=request.comment,
        )


@dataclass
class _StubClear:
    deleted: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)

    def execute(self, request: ClearFeedbackRequest) -> None:
        self.calls.append(request.request_id)
        if request.request_id not in self.deleted:
            raise FeedbackNotFoundError(request.request_id)
        self.deleted.discard(request.request_id)


@dataclass
class _StubGet:
    rows: dict[str, ResponseFeedback] = field(default_factory=dict)

    def execute(self, request: GetFeedbackRequest) -> ResponseFeedback:
        stored = self.rows.get(request.request_id)
        if stored is None:
            raise FeedbackNotFoundError(request.request_id)
        return stored


def _client(
    *,
    submit: _StubSubmit | None = None,
    clear: _StubClear | None = None,
    get: _StubGet | None = None,
) -> TestClient:
    app = create_app(cors_origins=())
    if submit is not None:
        app.dependency_overrides[get_submit_response_feedback] = lambda: submit
    if clear is not None:
        app.dependency_overrides[get_clear_response_feedback] = lambda: clear
    if get is not None:
        app.dependency_overrides[get_get_response_feedback] = lambda: get
    return TestClient(app, raise_server_exceptions=False)


def test_put_feedback_upserts_rating_and_query_metadata() -> None:
    submit = _StubSubmit()
    client = _client(submit=submit)
    response = client.put(
        "/api/v1/responses/req-1/feedback",
        params={"conversation_id": "conv-1", "client_message_id": "a-1"},
        json={"rating": "negative", "reason": "incorrect", "comment": "off"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "req-1"
    assert body["rating"] == "negative"
    assert body["reason"] == "incorrect"
    assert body["conversation_id"] == "conv-1"
    assert body["client_message_id"] == "a-1"
    assert body["prompt_key"] is None
    assert "workspace_id" not in body
    assert len(submit.calls) == 1
    assert submit.calls[0].request_id == "req-1"
    assert submit.calls[0].rating == "negative"


def test_put_feedback_rejects_reason_on_positive_rating() -> None:
    from application.errors import InputRejectedError

    class _RejectingSubmit:
        def execute(self, request: UpsertFeedbackRequest) -> ResponseFeedback:
            raise InputRejectedError(
                "reason is only allowed when rating is negative"
            )

    client = _client(submit=_RejectingSubmit())  # type: ignore[arg-type]
    response = client.put(
        "/api/v1/responses/req-1/feedback",
        json={"rating": "positive", "reason": "incorrect"},
    )
    assert response.status_code == 422


def test_put_feedback_rejects_unknown_reason() -> None:
    client = _client(submit=_StubSubmit())
    response = client.put(
        "/api/v1/responses/req-1/feedback",
        json={"rating": "negative", "reason": "not-a-reason"},
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_put_feedback_body_omits_prompt_fields() -> None:
    submit = _StubSubmit()
    client = _client(submit=submit)
    response = client.put(
        "/api/v1/responses/req-1/feedback",
        json={
            "rating": "positive",
            "prompt_key": "evil",
            "prompt_version": "v-evil",
        },
    )
    # Extra fields are ignored by default pydantic model; still must not reach use case.
    assert response.status_code == 200
    assert submit.calls[0].rating == "positive"
    assert not hasattr(submit.calls[0], "prompt_key")
    assert not hasattr(submit.calls[0], "prompt_version")
    assert response.json()["prompt_key"] is None
    assert response.json()["prompt_version"] is None


def test_delete_feedback_returns_204() -> None:
    clear = _StubClear(deleted={"req-1"})
    client = _client(clear=clear)
    response = client.delete("/api/v1/responses/req-1/feedback")
    assert response.status_code == 204
    assert clear.calls == ["req-1"]


def test_delete_missing_feedback_returns_404() -> None:
    client = _client(clear=_StubClear())
    response = client.delete("/api/v1/responses/req-missing/feedback")
    assert response.status_code == 404
    problem = response.json()
    assert problem["code"] == "feedback_not_found"


def test_get_feedback_returns_stored_rating() -> None:
    get = _StubGet(
        rows={
            "req-1": ResponseFeedback(
                workspace_id="ws-a",
                request_id="req-1",
                rating="positive",
                created_at="2026-09-17T10:00:00+00:00",
                updated_at="2026-09-17T10:00:00+00:00",
            )
        }
    )
    client = _client(get=get)
    response = client.get("/api/v1/responses/req-1/feedback")
    assert response.status_code == 200
    assert response.json()["rating"] == "positive"


def test_get_missing_feedback_returns_404() -> None:
    client = _client(get=_StubGet())
    response = client.get("/api/v1/responses/req-missing/feedback")
    assert response.status_code == 404
    assert response.json()["code"] == "feedback_not_found"
