"""Problem Details envelope at the HTTP adapter surface."""

from fastapi.testclient import TestClient

from domain.errors import ProviderError
from presentation.http.app import create_app


def test_unknown_route_returns_problem_json() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert body["code"] == "not_found"
    assert "Traceback" not in response.text


def test_request_validation_returns_problem_with_errors() -> None:
    app = create_app()

    @app.get("/api/v1/_probe_validation")
    def _probe(limit: int) -> dict[str, int]:
        return {"limit": limit}

    client = TestClient(app)
    response = client.get("/api/v1/_probe_validation", params={"limit": "not-an-int"})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["errors"]
    assert all("pointer" in err and "detail" in err for err in body["errors"])
    assert "Traceback" not in response.text


def test_mapped_exception_returns_problem_without_traceback() -> None:
    app = create_app()

    @app.get("/api/v1/_probe_provider")
    def _probe() -> None:
        raise ProviderError("sk-leaked-secret\nTraceback (most recent call last):")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/_probe_provider")

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "provider_error"
    assert body["detail"] == "The model provider could not complete the request."
    assert "sk-leaked" not in response.text
    assert "Traceback" not in response.text
