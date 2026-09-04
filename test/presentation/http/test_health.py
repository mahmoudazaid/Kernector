"""Health endpoint — unversioned operational readiness."""

from fastapi.testclient import TestClient

from presentation.http.app import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_favicon_returns_no_content() -> None:
    response = TestClient(create_app()).get("/favicon.ico")

    assert response.status_code == 204
