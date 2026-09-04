"""Capabilities prove-out — settings via dependency_overrides only."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from presentation.http.app import create_app
from presentation.http.deps import get_settings


def _settings(*, provider: str = "openrouter", packs: tuple[str, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        provider=provider,
        domain_tools=SimpleNamespace(enabled_packs=packs),
    )


def test_capabilities_returns_providers_and_flags() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _settings(
        provider="ollama",
        packs=("software-delivery",),
    )
    client = TestClient(app)

    response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["providers"] == ["openrouter", "ollama"]
    assert body["default_provider"] == "ollama"
    assert body["software_delivery_tools_enabled"] is True


def test_capabilities_reports_tools_disabled_when_pack_absent() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _settings(packs=())
    client = TestClient(app)

    response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["software_delivery_tools_enabled"] is False
