"""OpenAPI describes real response and Problem Details contracts."""

from fastapi.testclient import TestClient

from presentation.http.app import create_app

_PROBLEM = "application/problem+json"
_ERROR_STATUSES = {
    "/health": ("405",),
    "/api/v1/capabilities": ("405", "500"),
}


def test_openapi_includes_health_and_capabilities_schemas() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()

    assert "/health" in schema["paths"]
    assert "/api/v1/capabilities" in schema["paths"]

    health = schema["paths"]["/health"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    caps = schema["paths"]["/api/v1/capabilities"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]

    components = schema["components"]["schemas"]
    health_name = health.get("$ref", "").rsplit("/", 1)[-1] or "HealthResponse"
    caps_name = caps.get("$ref", "").rsplit("/", 1)[-1] or "CapabilitiesResponse"

    assert "status" in components[health_name]["properties"]
    assert set(components[caps_name]["properties"]) >= {
        "providers",
        "default_provider",
        "software_delivery_tools_enabled",
    }


def test_openapi_includes_problem_schema() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    components = schema["components"]["schemas"]

    assert "Problem" in components
    props = components["Problem"]["properties"]
    assert {"type", "title", "status", "detail", "code"} <= set(props)


def test_openapi_error_responses_use_problem_json_only() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()

    for path, statuses in _ERROR_STATUSES.items():
        responses = schema["paths"][path]["get"]["responses"]
        for status in statuses:
            content = responses[status]["content"]
            assert list(content) == [_PROBLEM], (
                f"{path} status {status} media types={list(content)}"
            )
            ref = content[_PROBLEM]["schema"].get("$ref", "")
            assert ref.endswith("/Problem"), f"{path} {status} schema ref={ref}"


def test_openapi_does_not_declare_unreachable_error_statuses() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    health = schema["paths"]["/health"]["get"]["responses"]
    caps = schema["paths"]["/api/v1/capabilities"]["get"]["responses"]

    assert "404" not in health
    assert "422" not in health
    assert "500" not in health
    assert "404" not in caps
    assert "422" not in caps
    assert "502" not in caps
