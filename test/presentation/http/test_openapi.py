"""OpenAPI describes real response and Problem Details contracts."""

from fastapi.testclient import TestClient

from presentation.http.app import create_app


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
