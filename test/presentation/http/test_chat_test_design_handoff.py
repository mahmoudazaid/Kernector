"""Chat ask routes Test Design via TurnRouter (no presentation pre-handoff)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from application.contracts import AskRequest, AskResponse
from composition.test_design import build_test_design_handoff_from_request
from composition.tool_augmented_ask import ToolAugmentedAsk
from composition.workflow_signals import (
    TEST_DESIGN_CLARIFY_ANSWER,
    build_drive_export_workflow_signal,
    build_test_design_workflow_signal,
)
from infrastructure.config import DomainToolSettings
from presentation.http.app import create_app
from presentation.http.deps import get_ask_factory, get_settings


class _ExplodingAsk:
    def execute(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("grounded/general ask must not run on this path")


class _ExplodingRunner:
    def run(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("tool runner must not run on this path")


class _RecordingAsk:
    def __init__(self) -> None:
        self.calls = 0

    def execute(
        self,
        request: AskRequest,
        settings: Mapping[str, object] | None = None,
    ) -> AskResponse:
        del request, settings
        self.calls += 1
        return AskResponse(answer="grounded")


def _routed_factory(
    settings,
    *,
    grounded: object | None = None,
    export_enabled: bool = False,
    draft_ready: bool = False,
    clarification_context_store: object | None = None,
    runner: object | None = None,
):
    grounded_ask = grounded if grounded is not None else _ExplodingAsk()
    tool_runner = runner if runner is not None else _ExplodingRunner()

    def factory(runtime=None, *, source_locator=None):  # noqa: ANN001
        del runtime

        def build_handoff(request: AskRequest):
            return build_test_design_handoff_from_request(
                settings=settings,
                request=request,
                source_locator=source_locator,
            )

        return ToolAugmentedAsk(
            grounded_ask,  # type: ignore[arg-type]
            runner=tool_runner,  # type: ignore[arg-type]
            signals=(
                build_test_design_workflow_signal(enabled=True),
                build_drive_export_workflow_signal(
                    export_enabled=export_enabled,
                    draft_ready=lambda _cid: draft_ready,
                ),
            ),
            ask_general=_ExplodingAsk(),
            pack_id="software-delivery",
            build_test_design_handoff=build_handoff,
            clarification_context_store=clarification_context_store,
        )

    return factory


def test_test_design_ready_handoff_does_not_call_grounded_ask() -> None:
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(settings)
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/ask",
        json={
            "query": "Design tests for mahmoudazaid/Kernector#293",
            "history": [],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["action"]["kind"] == "start_workflow"
    assert body["action"]["source_locator"] == {
        "provider": "github",
        "locator": "mahmoudazaid/Kernector#293",
    }
    assert body["citations"] == []
    assert body["run"]["intent"] == "tool_workflow"
    assert body["run"]["path"] == "tools"


@pytest.mark.parametrize(
    "query",
    [
        "Please design tests for mahmoudazaid/Kernector#293",
        "Can you design tests for mahmoudazaid/Kernector#293?",
        "Could you start test design for mahmoudazaid/Kernector#293",
    ],
)
def test_prefixed_test_design_command_with_locator_starts_workflow(
    query: str,
) -> None:
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(settings)
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/ask",
        json={"query": query, "history": []},
    )
    assert response.status_code == 200, query
    body = response.json()
    assert body["action"]["kind"] == "start_workflow", query
    assert body["run"]["intent"] == "tool_workflow", query


def test_test_design_handoff_rejects_mismatched_source_locator() -> None:
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(settings)
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/ask",
        json={
            "query": "Design tests for mahmoudazaid/Kernector#293",
            "history": [],
            "source_locator": {
                "provider": "github",
                "locator": "other/repo#1",
            },
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_issue_304_command_without_issue_clarifies_without_rag() -> None:
    ask = _RecordingAsk()
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(
        settings, grounded=ask
    )
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/ask",
        json={"query": "design test", "history": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert ask.calls == 0
    assert body["action"] is None
    assert body["answer"] == TEST_DESIGN_CLARIFY_ANSWER
    assert body["run"]["intent"] == "clarification"
    assert body["run"]["path"] == "clarification"


def test_issue_310_partial_export_clarifies_without_rag() -> None:
    ask = _RecordingAsk()
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(
            enabled_packs=("software-delivery",),
            agent_loop=True,
        ),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(
        settings, grounded=ask, export_enabled=True, draft_ready=True
    )
    client = TestClient(app)
    for query in ("export", "export the selected tests", "send this to Drive"):
        ask.calls = 0
        response = client.post(
            "/api/v1/chat/ask",
            json={"query": query, "history": [], "conversation_id": "c1"},
        )
        assert response.status_code == 200, query
        body = response.json()
        assert ask.calls == 0, query
        assert body["run"]["intent"] == "clarification"
        assert body["run"]["path"] == "clarification"
        assert "Google Drive" in body["answer"]


def test_issue_310_clear_export_missing_payload_clarifies_without_rag() -> None:
    ask = _RecordingAsk()
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(
            enabled_packs=("software-delivery",),
            agent_loop=True,
        ),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(
        settings, grounded=ask, export_enabled=True, draft_ready=False
    )
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/ask",
        json={
            "query": "export to google drive",
            "history": [],
            "conversation_id": "c1",
        },
    )
    assert response.status_code == 200
    assert ask.calls == 0
    assert response.json()["run"]["intent"] == "clarification"


def test_disabled_drive_export_clarifies_without_rag() -> None:
    ask = _RecordingAsk()
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(
            enabled_packs=("software-delivery",),
            agent_loop=False,
        ),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(
        settings, grounded=ask, export_enabled=False, draft_ready=True
    )
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/ask",
        json={"query": "export to google drive", "history": []},
    )
    assert response.status_code == 200
    assert ask.calls == 0
    assert response.json()["run"]["intent"] == "clarification"


def test_test_design_discussion_with_multiple_issues_falls_through_to_ask() -> None:
    ask = _RecordingAsk()
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(
        settings, grounded=ask
    )
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/ask",
        json={
            "query": "Compare the test coverage of acme/web#10 and acme/api#11",
            "history": [],
        },
    )
    assert response.status_code == 200
    assert ask.calls == 1
    assert response.json().get("action") is None


def test_test_design_explicit_command_with_multiple_issues_returns_422() -> None:
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(settings)
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/ask",
        json={
            "query": "Design tests for acme/web#10 and acme/api#11",
            "history": [],
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


@pytest.mark.parametrize(
    "query",
    [
        "How does test design work in this repo?",
        "Who owns test design here?",
        "What do the docs say about test design?",
        "Can you explain the coverage plan we agreed on last sprint?",
        "Summarize our test design guidelines from the docs",
    ],
)
def test_test_design_topical_phrase_falls_through_to_grounded_ask(
    query: str,
) -> None:
    ask = _RecordingAsk()
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(
        settings, grounded=ask
    )
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/ask",
        json={"query": query, "history": []},
    )
    assert response.status_code == 200
    assert ask.calls == 1
    assert response.json().get("action") is None


def test_bare_issue_number_command_clarifies_not_rag() -> None:
    ask = _RecordingAsk()
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(
        settings, grounded=ask
    )
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/ask",
        json={"query": "Design tests for 293", "history": []},
    )
    assert response.status_code == 200
    assert ask.calls == 0
    assert response.json()["run"]["intent"] == "clarification"


def test_follow_up_locator_after_clarify_starts_test_design() -> None:
    from composition.clarification_context import InMemoryClarificationContextStore

    ask = _RecordingAsk()
    store = InMemoryClarificationContextStore()
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(
        settings, grounded=ask, clarification_context_store=store
    )
    client = TestClient(app)
    first = client.post(
        "/api/v1/chat/ask",
        json={
            "query": "design test cases",
            "history": [],
            "conversation_id": "conv-follow-1",
        },
    )
    assert first.status_code == 200
    assert first.json()["run"]["intent"] == "clarification"
    assert ask.calls == 0

    second = client.post(
        "/api/v1/chat/ask",
        json={
            "query": "mahmoudazaid/Kernector/218",
            "history": [],
            "conversation_id": "conv-follow-1",
        },
    )
    assert second.status_code == 200
    body = second.json()
    assert ask.calls == 0
    assert body["run"]["intent"] == "tool_workflow"
    assert body["action"] is not None
    assert body["action"]["label"] == "Start Test Design"
    assert body["action"]["source_locator"]["locator"] == (
        "mahmoudazaid/Kernector#218"
    )


def test_follow_up_bare_number_after_clarify_stays_clarification() -> None:
    from composition.clarification_context import InMemoryClarificationContextStore

    ask = _RecordingAsk()
    store = InMemoryClarificationContextStore()
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(
        settings, grounded=ask, clarification_context_store=store
    )
    client = TestClient(app)
    client.post(
        "/api/v1/chat/ask",
        json={
            "query": "design test cases",
            "history": [],
            "conversation_id": "conv-bare-1",
        },
    )
    second = client.post(
        "/api/v1/chat/ask",
        json={
            "query": "218",
            "history": [],
            "conversation_id": "conv-bare-1",
        },
    )
    assert second.status_code == 200
    assert ask.calls == 0
    assert second.json()["run"]["intent"] == "clarification"
    assert second.json()["answer"] == TEST_DESIGN_CLARIFY_ANSWER


def test_pivot_after_clarify_clears_context_and_uses_rag() -> None:
    from composition.clarification_context import InMemoryClarificationContextStore

    ask = _RecordingAsk()
    store = InMemoryClarificationContextStore()
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(
        settings, grounded=ask, clarification_context_store=store
    )
    client = TestClient(app)
    client.post(
        "/api/v1/chat/ask",
        json={
            "query": "design test cases",
            "history": [],
            "conversation_id": "conv-pivot-1",
        },
    )
    second = client.post(
        "/api/v1/chat/ask",
        json={
            "query": "What do the docs say about auth?",
            "history": [],
            "conversation_id": "conv-pivot-1",
        },
    )
    assert second.status_code == 200
    assert ask.calls == 1
    assert second.json()["run"]["path"] == "rag"
    assert store.get("conv-pivot-1") is None
    # Locator alone after pivot must not revive the workflow.
    third = client.post(
        "/api/v1/chat/ask",
        json={
            "query": "mahmoudazaid/Kernector#218",
            "history": [],
            "conversation_id": "conv-pivot-1",
        },
    )
    assert third.status_code == 200
    assert ask.calls == 2
    assert third.json().get("action") is None


def test_drive_export_yes_follow_up_never_falls_to_rag() -> None:
    from composition.clarification_context import InMemoryClarificationContextStore
    from composition.workflow_signals import DRIVE_MISSING_PAYLOAD_CLARIFY_ANSWER

    ask = _RecordingAsk()
    store = InMemoryClarificationContextStore()
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(
            enabled_packs=("software-delivery",),
            agent_loop=True,
        ),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(
        settings,
        grounded=ask,
        export_enabled=True,
        draft_ready=False,
        clarification_context_store=store,
    )
    client = TestClient(app)
    first = client.post(
        "/api/v1/chat/ask",
        json={
            "query": "export",
            "history": [],
            "conversation_id": "conv-drive-1",
        },
    )
    assert first.status_code == 200
    assert first.json()["run"]["intent"] == "clarification"
    assert ask.calls == 0

    second = client.post(
        "/api/v1/chat/ask",
        json={
            "query": "yes",
            "history": [],
            "conversation_id": "conv-drive-1",
        },
    )
    assert second.status_code == 200
    body = second.json()
    assert ask.calls == 0
    assert body["run"]["intent"] == "clarification"
    assert body["run"]["path"] == "clarification"
    assert body["answer"] == DRIVE_MISSING_PAYLOAD_CLARIFY_ANSWER


def test_drive_export_yes_follow_up_runs_tools_when_draft_ready() -> None:
    from composition.clarification_context import InMemoryClarificationContextStore
    from composition.tool_augmented_ask import ToolRunOutcome

    class _RecordingRunner:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            self.calls += 1
            return ToolRunOutcome(answer="exported")

    ask = _RecordingAsk()
    runner = _RecordingRunner()
    store = InMemoryClarificationContextStore()
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(
            enabled_packs=("software-delivery",),
            agent_loop=True,
        ),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: _routed_factory(
        settings,
        grounded=ask,
        export_enabled=True,
        draft_ready=True,
        clarification_context_store=store,
        runner=runner,
    )
    client = TestClient(app)
    client.post(
        "/api/v1/chat/ask",
        json={
            "query": "export",
            "history": [],
            "conversation_id": "conv-drive-2",
        },
    )
    second = client.post(
        "/api/v1/chat/ask",
        json={
            "query": "yes",
            "history": [],
            "conversation_id": "conv-drive-2",
        },
    )
    assert second.status_code == 200
    body = second.json()
    assert ask.calls == 0
    assert runner.calls == 1
    assert body["run"]["intent"] == "tool_workflow"
    assert body["answer"] == "exported"
    assert store.get("conv-drive-2") is None
