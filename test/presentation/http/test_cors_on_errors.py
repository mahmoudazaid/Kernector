"""CORS headers must survive mapped error responses (ExceptionMiddleware path)."""

from fastapi.testclient import TestClient

from application.errors import ConfigurationError
from domain.errors import ProviderError
from presentation.http.app import create_app
from presentation.http.deps import get_settings

_ORIGIN = "http://localhost:3000"


def test_provider_error_response_includes_cors_allow_origin() -> None:
    app = create_app(cors_origins=(_ORIGIN,))

    @app.get("/api/v1/_probe_provider_cors")
    def _probe() -> None:
        raise ProviderError("upstream failure")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        "/api/v1/_probe_provider_cors",
        headers={"Origin": _ORIGIN},
    )

    assert response.status_code == 502
    assert response.headers.get("access-control-allow-origin") == _ORIGIN


def test_configuration_error_from_settings_dep_includes_cors_allow_origin() -> None:
    app = create_app(cors_origins=(_ORIGIN,))

    def _boom_settings() -> None:
        raise ConfigurationError("missing credential")

    app.dependency_overrides[get_settings] = _boom_settings
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        "/api/v1/capabilities",
        headers={"Origin": _ORIGIN},
    )

    assert response.status_code == 500
    assert response.json()["code"] == "configuration_error"
    assert response.headers.get("access-control-allow-origin") == _ORIGIN


def test_request_validation_still_returns_problem_with_cors() -> None:
    """RequestValidationError must beat the ValueError handler via MRO."""
    app = create_app(cors_origins=(_ORIGIN,))

    @app.get("/api/v1/_probe_validation_cors")
    def _probe(limit: int) -> dict[str, int]:
        return {"limit": limit}

    client = TestClient(app)
    response = client.get(
        "/api/v1/_probe_validation_cors",
        params={"limit": "not-an-int"},
        headers={"Origin": _ORIGIN},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["errors"]
    assert response.headers.get("access-control-allow-origin") == _ORIGIN


def test_mapped_provider_error_is_not_re_raised_to_asgi() -> None:
    """ExceptionMiddleware consumes the error; uvicorn must not see a re-raise."""
    app = create_app()

    @app.get("/api/v1/_probe_provider_no_reraise")
    def _probe() -> None:
        raise ProviderError("should stay in the handler")

    # raise_server_exceptions=True would surface a ServerErrorMiddleware re-raise.
    client = TestClient(app, raise_server_exceptions=True)
    response = client.get("/api/v1/_probe_provider_no_reraise")

    assert response.status_code == 502
    assert response.json()["code"] == "provider_error"


def test_method_not_allowed_forwards_allow_header() -> None:
    client = TestClient(create_app())
    response = client.post("/health")

    assert response.status_code == 405
    assert response.headers["content-type"].startswith("application/problem+json")
    allow = response.headers.get("allow", "")
    assert "GET" in allow.upper()
