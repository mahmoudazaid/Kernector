"""Chat ask bypasses RAG when Test Design handoff applies."""

from __future__ import annotations

from dataclasses import replace

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
