"""OpenAPI describes real response and Problem Details contracts."""

from fastapi.testclient import TestClient

from presentation.http.app import create_app

_PROBLEM = "application/problem+json"
# path -> (http_method, expected error status codes as strings)
_ERROR_STATUSES: dict[str, tuple[str, tuple[str, ...]]] = {
    "/health": ("get", ("405",)),
    "/api/v1/settings": ("get", ("405", "500")),
    "/api/v1/ollama/status": ("get", ("405", "409", "500")),
    "/api/v1/chat/ask": ("post", ("405", "409", "422", "500", "502")),
    "/api/v1/connectors/google-drive": ("get", ("405", "500")),
    "/api/v1/connectors/google-drive/sync": ("post", ("405", "409", "500", "502")),
    "/api/v1/connectors/google-drive/oauth/start": ("get", ("405", "500")),
    "/api/v1/connectors/google-drive/oauth/callback": ("get", ("405", "500")),
}


_DOCUMENTS_ERROR_STATUSES: dict[tuple[str, str], tuple[str, ...]] = {
    ("/api/v1/documents", "get"): ("405", "500"),
    ("/api/v1/documents", "post"): ("405", "409", "413", "422", "500"),
    ("/api/v1/documents/{source_id}", "put"): (
        "404",
        "405",
        "409",
        "413",
        "422",
        "500",
    ),
    ("/api/v1/documents/{source_id}", "delete"): ("405", "409", "422", "500"),
    ("/api/v1/documents/{source_id}/content", "get"): (
        "404",
        "405",
        "422",
        "500",
    ),
    ("/api/v1/documents/{source_id}/download", "get"): (
        "404",
        "405",
        "422",
        "500",
    ),
    ("/api/v1/documents/{source_id}/chunks", "get"): ("404", "405", "422", "500"),
}


def test_openapi_includes_health_and_settings_schemas() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()

    assert "/health" in schema["paths"]
    assert "/api/v1/settings" in schema["paths"]
    assert "/api/v1/capabilities" not in schema["paths"]
    assert "CapabilitiesResponse" not in schema["components"]["schemas"]
    assert "DocumentUploadConstraintsResponse" not in schema["components"]["schemas"]

    health = schema["paths"]["/health"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    settings = schema["paths"]["/api/v1/settings"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]

    components = schema["components"]["schemas"]
    health_name = health.get("$ref", "").rsplit("/", 1)[-1] or "HealthResponse"
    settings_name = (
        settings.get("$ref", "").rsplit("/", 1)[-1] or "RuntimeSettingsResponse"
    )

    assert "status" in components[health_name]["properties"]
    assert set(components[settings_name]["properties"]) >= {
        "providers",
        "default_provider",
        "enabled_packs",
        "constraints",
    }
    document_list = components["DocumentListResponse"]["properties"]
    assert set(document_list) == {"documents"}


def test_openapi_includes_problem_schema() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    components = schema["components"]["schemas"]

    assert "Problem" in components
    props = components["Problem"]["properties"]
    assert {"type", "title", "status", "detail", "code"} <= set(props)


def test_openapi_hub_source_type_is_named_component() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    components = schema["components"]["schemas"]
    assert "HubSourceType" in components
    assert set(components["HubSourceType"]["enum"]) == {
        "knowledge_document",
        "google_drive",
    }
    chunks = schema["paths"]["/api/v1/documents/{source_id}/chunks"]["get"]
    source_type = next(
        param
        for param in chunks["parameters"]
        if param["name"] == "source_type"
    )
    assert source_type["schema"] == {"$ref": "#/components/schemas/HubSourceType"}


def test_openapi_error_responses_use_problem_json_only() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()

    for path, (method, statuses) in _ERROR_STATUSES.items():
        responses = schema["paths"][path][method]["responses"]
        for status in statuses:
            content = responses[status]["content"]
            assert list(content) == [_PROBLEM], (
                f"{path} {method} status {status} media types={list(content)}"
            )
            ref = content[_PROBLEM]["schema"].get("$ref", "")
            assert ref.endswith("/Problem"), f"{path} {status} schema ref={ref}"

    for (path, method), statuses in _DOCUMENTS_ERROR_STATUSES.items():
        responses = schema["paths"][path][method]["responses"]
        for status in statuses:
            content = responses[status]["content"]
            assert list(content) == [_PROBLEM], (
                f"{path} {method} status {status} media types={list(content)}"
            )
            ref = content[_PROBLEM]["schema"].get("$ref", "")
            assert ref.endswith("/Problem"), f"{path} {status} schema ref={ref}"


def test_openapi_google_drive_delete_declares_problem_errors() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    delete = schema["paths"]["/api/v1/connectors/google-drive"]["delete"]["responses"]
    assert "204" in delete
    for status in ("405", "409", "500"):
        content = delete[status]["content"]
        assert list(content) == [_PROBLEM]


def test_openapi_documents_delete_does_not_declare_404() -> None:
    """Delete unknown is a 204 no-op — 404 must not appear in the contract."""
    schema = TestClient(create_app()).get("/openapi.json").json()
    delete = schema["paths"]["/api/v1/documents/{source_id}"]["delete"]["responses"]

    assert "404" not in delete
    assert "204" in delete


def test_openapi_does_not_declare_unreachable_error_statuses() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()
    health = schema["paths"]["/health"]["get"]["responses"]
    settings = schema["paths"]["/api/v1/settings"]["get"]["responses"]

    assert "404" not in health
    assert "422" not in health
    assert "500" not in health
    assert "404" not in settings
    assert "422" not in settings
    assert "502" not in settings
