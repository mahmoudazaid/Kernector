"""HTTP schema projection for Software Delivery tool-run views."""

from __future__ import annotations

from typing import Any, get_args, get_origin

from pydantic import BaseModel

from composition.software_delivery.tools import SoftwareDeliveryRunView
from presentation.cli.export_openapi import export_openapi_document
from presentation.http.schemas import (
    ToolCallResponse,
    ToolRunResponse,
    tool_run_response,
)
from test.software_delivery_views import software_delivery_run_view

_RETIRED_FIELDS = {"risk", "test_cases", "markdown"}
_RETIRED_SCHEMAS = {
    "RiskScoreResponse",
    "RiskFactorResponse",
    "TestCasesResponse",
    "TestCaseResponse",
}


def test_tool_run_response_projects_a_typed_view() -> None:
    view = software_delivery_run_view()

    assert tool_run_response(view).model_dump() == {
        "summary": "Export finished.",
        "calls": [
            {
                "tool_name": "pack.example_tool",
                "ok": True,
                "summary": "Ran the example tool",
            },
            {
                "tool_name": "software_delivery.export_test_cases_google_drive",
                "ok": True,
                "summary": "Exported test cases to Google Drive",
            },
        ],
        "export_destination_required": False,
        "drive_file_id": "file-1",
        "drive_file_name": "test-cases.md",
    }


def test_tool_run_response_projects_an_empty_view() -> None:
    view = SoftwareDeliveryRunView(
        summary="No tools produced structured results.",
        calls=(),
    )

    assert tool_run_response(view).model_dump() == {
        "summary": "No tools produced structured results.",
        "calls": [],
        "export_destination_required": False,
        "drive_file_id": "",
        "drive_file_name": "",
    }


def test_tool_run_response_has_no_retired_tool_fields() -> None:
    assert set(ToolRunResponse.model_fields).isdisjoint(_RETIRED_FIELDS)


def test_openapi_contract_has_no_retired_tool_schemas() -> None:
    document = export_openapi_document()
    schemas = document["components"]["schemas"]  # type: ignore[index]

    assert set(schemas).isdisjoint(_RETIRED_SCHEMAS)
    assert set(schemas["ToolRunResponse"]["properties"]).isdisjoint(
        _RETIRED_FIELDS
    )


def test_tool_run_projection_fields_are_locked() -> None:
    """Field names, annotations, requiredness, and wire aliases must stay pinned."""
    expected = {
        ToolCallResponse: {
            ("tool_name", str, True),
            ("ok", bool, True),
            ("summary", str, False),
        },
        ToolRunResponse: {
            ("summary", str, True),
            ("calls", list[ToolCallResponse], True),
            ("export_destination_required", bool, False),
            ("drive_file_id", str, False),
            ("drive_file_name", str, False),
        },
    }

    reachable = _reachable_response_models(ToolRunResponse)
    assert reachable == set(expected)

    for model, fields in expected.items():
        assert {
            (name, field.annotation, field.is_required())
            for name, field in model.model_fields.items()
        } == fields
        for name, field in model.model_fields.items():
            assert field.serialization_alias is None, (model.__name__, name)


def _reachable_response_models(root: type[BaseModel]) -> set[type[BaseModel]]:
    """Walk nested Pydantic annotations reachable from ``root``."""
    seen: set[type[BaseModel]] = set()
    stack: list[type[BaseModel]] = [root]
    while stack:
        model = stack.pop()
        if model in seen:
            continue
        seen.add(model)
        for field in model.model_fields.values():
            for candidate in _model_types_in_annotation(field.annotation):
                if candidate not in seen:
                    stack.append(candidate)
    return seen


def _model_types_in_annotation(annotation: Any) -> list[type[BaseModel]]:
    origin = get_origin(annotation)
    if origin is None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return [annotation]
        return []
    nested: list[type[BaseModel]] = []
    for arg in get_args(annotation):
        nested.extend(_model_types_in_annotation(arg))
    return nested
