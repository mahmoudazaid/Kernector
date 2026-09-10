"""Catalog workspace must not block HTTP bootstrap."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from application.errors import ConfigurationError
from composition import container as composition_container
from infrastructure.config import load_settings
from presentation.http.app import create_app


def test_create_app_and_health_work_without_catalog_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unrelated entry points must not inherit a catalog-only precondition."""
    monkeypatch.delenv("DOCUMENT_CATALOG_WORKSPACE_ID", raising=False)
    app = create_app()
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert load_settings().document_catalog.workspace_id is None


def test_build_document_catalog_fails_when_workspace_absent_after_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DOCUMENT_CATALOG_WORKSPACE_ID", raising=False)
    settings = load_settings()
    assert settings.document_catalog.workspace_id is None
    with pytest.raises(ConfigurationError, match="DOCUMENT_CATALOG_WORKSPACE_ID"):
        composition_container.build_document_catalog(settings)
