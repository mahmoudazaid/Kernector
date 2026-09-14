"""Chat ask bypasses RAG when Test Design handoff applies."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from infrastructure.config import DomainToolSettings
from presentation.http.app import create_app
from presentation.http.deps import get_ask_factory, get_settings


class _ExplodingAsk:
    def execute(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("ask.execute must not run on Test Design handoff")


def test_test_design_handoff_does_not_call_ask_execute() -> None:
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: (
        lambda _runtime=None: _ExplodingAsk()
    )
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
    assert "ask.execute" not in body["answer"]


def test_test_design_handoff_rejects_mismatched_source_locator() -> None:
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = lambda: (
        lambda _runtime=None: _ExplodingAsk()
    )
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


class _RecordingAsk:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        from application.contracts import AskResponse

        self.calls += 1
        return AskResponse(answer="grounded")


def _pack_client(*, ask_factory):
    base = get_settings()
    settings = replace(
        base,
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    app = create_app(cors_origins=())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ask_factory] = ask_factory
    return TestClient(app)


def test_test_design_discussion_with_multiple_issues_falls_through_to_ask() -> None:
    ask = _RecordingAsk()
    client = _pack_client(ask_factory=lambda: (lambda _runtime=None: ask))
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
    client = _pack_client(
        ask_factory=lambda: (lambda _runtime=None: _ExplodingAsk())
    )
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
        "Design tests for 293",
        "Can you explain the coverage plan we agreed on last sprint?",
    ],
)
def test_test_design_topical_phrase_without_issue_falls_through_to_ask(
    query: str,
) -> None:
    ask = _RecordingAsk()
    client = _pack_client(ask_factory=lambda: (lambda _runtime=None: ask))
    response = client.post(
        "/api/v1/chat/ask",
        json={"query": query, "history": []},
    )
    assert response.status_code == 200
    assert ask.calls == 1
    assert response.json().get("action") is None
