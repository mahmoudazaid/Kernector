"""POST /api/v1/chat/threads/{id}/approvals/{id} — HITL decision (#214)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from application.decide_tool_approval import (
    DecideToolApprovalRequest,
    DecideToolApprovalResponse,
)
from domain.errors import ToolApprovalConflictError, ToolApprovalNotFoundError
from domain.models import AgentTurnResult
from domain.tool_approval import PendingToolApproval
from presentation.http.app import create_app
from presentation.http.deps import get_short_term_memory_runtime


@dataclass
class _StubDecide:
    response: DecideToolApprovalResponse | None = None
    error: BaseException | None = None
    last: DecideToolApprovalRequest | None = None

    def execute(self, request: DecideToolApprovalRequest) -> DecideToolApprovalResponse:
        self.last = request
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


@dataclass
class _StubRuntime:
    decide: _StubDecide

    def decide_tool_approval(self) -> _StubDecide:
        return self.decide


def _client(runtime: _StubRuntime) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_short_term_memory_runtime] = lambda: runtime
    return TestClient(app, raise_server_exceptions=False)


def test_decide_approval_returns_answer_and_cancelled_flag() -> None:
    decide = _StubDecide(
        response=DecideToolApprovalResponse(
            turn=AgentTurnResult(content="Export cancelled."),
            cancelled=True,
            pending_approval=None,
        )
    )
    client = _client(_StubRuntime(decide))

    response = client.post(
        "/api/v1/chat/threads/conv-1/approvals/appr-9",
        json={"decision": "reject"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == (
        "Understood. I cancelled the export and did not write anything "
        "to Google Drive."
    )
    assert body["cancelled"] is True
    assert body["pending_approval"] is None
    assert decide.last is not None
    assert decide.last.conversation_id == "conv-1"
    assert decide.last.approval_id == "appr-9"
    assert decide.last.decision == "reject"


def test_decide_approval_conflict_is_problem_details() -> None:
    decide = _StubDecide(error=ToolApprovalConflictError("already decided"))
    client = _client(_StubRuntime(decide))

    response = client.post(
        "/api/v1/chat/threads/conv-1/approvals/appr-9",
        json={"decision": "approve"},
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "tool_approval_conflict"


def test_decide_approval_not_found_is_problem_details() -> None:
    decide = _StubDecide(error=ToolApprovalNotFoundError("missing"))
    client = _client(_StubRuntime(decide))

    response = client.post(
        "/api/v1/chat/threads/conv-1/approvals/missing",
        json={"decision": "approve"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "tool_approval_not_found"


def test_chat_ask_projects_pending_approval_from_tool_view() -> None:
    from application.contracts import AskResponse
    from composition.software_delivery_tools import SoftwareDeliveryRunView
    from presentation.http.deps import get_ask_factory

    pending = PendingToolApproval(
        approval_id="c1",
        tool_name="software_delivery.export_test_cases_google_drive",
        title="Export test cases to Google Drive",
        summary="Write selected titles as Markdown.",
        destination_label="QA / Sprint 3",
        file_name="issue-482.md",
        selected_title_count=2,
    )
    view = SoftwareDeliveryRunView(
        summary="Waiting for approval before continuing.",
        calls=(),
        pending_approval=pending,
    )

    class _Ask:
        def execute(self, request, settings=None):
            del request, settings
            return AskResponse(answer="Waiting for approval before continuing.")

        def consume_tool_run_view(self):
            return view

    app = create_app()
    app.dependency_overrides[get_ask_factory] = lambda: (
        lambda _runtime=None, **_kwargs: _Ask()
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/chat/ask",
        json={"query": "export to drive", "conversation_id": "conv-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pending_approval"]["approval_id"] == "c1"
    assert body["pending_approval"]["destination_label"] == "QA / Sprint 3"
    assert "folder" not in response.text.lower()


def test_put_export_destination_returns_label() -> None:
    from presentation.http.deps import get_test_design_facade

    class _Facade:
        def set_export_destination(
            self,
            conversation_id: str,
            *,
            folder_id: str,
            destination_label: str | None = None,
        ) -> str:
            assert conversation_id == "conv-1"
            assert folder_id == "root"
            assert destination_label == "Home"
            return "Home"

    app = create_app()
    app.dependency_overrides[get_test_design_facade] = lambda: _Facade()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.put(
        "/api/v1/chat/threads/conv-1/export-destination",
        json={"folder_id": "root", "destination_label": "Home"},
    )
    assert response.status_code == 200
    assert response.json() == {"destination_label": "Home"}
