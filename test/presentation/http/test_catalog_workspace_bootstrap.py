"""Catalog workspace must not block HTTP bootstrap."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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


def test_create_app_and_health_work_with_malformed_catalog_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "bad id")
    app = create_app()
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert load_settings().document_catalog.workspace_id == "bad id"


def test_create_app_and_health_work_with_retired_catalog_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCUMENT_CATALOG_BACKEND", "sql")
    app = create_app()
    response = TestClient(app).get("/health")
    assert response.status_code == 200


def test_create_app_and_health_work_with_blank_sql_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCUMENT_CATALOG_SQL_PATH", "")
    app = create_app()
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert load_settings().document_catalog.sql_path is None


def test_create_app_and_health_work_with_malformed_drive_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "bad id")
    app = create_app()
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert load_settings().google_drive.folder_id == "bad id"


def test_list_documents_reports_configuration_error_without_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DOCUMENT_CATALOG_WORKSPACE_ID", raising=False)
    app = create_app()
    response = TestClient(app).get("/api/v1/documents")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "configuration_error"
    assert body["detail"] == "The service is not configured correctly."
