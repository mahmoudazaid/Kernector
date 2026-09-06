"""HTTP schema projection for Software Delivery tool-run views."""

from __future__ import annotations

from typing import Any, get_args, get_origin

from pydantic import BaseModel

from composition.software_delivery_tools import SoftwareDeliveryRunView
from presentation.http.schemas import ToolCallResponse, ToolRunResponse, tool_run_response
from test.software_delivery_views import software_delivery_run_view


def test_tool_run_response_projects_a_typed_view() -> None:
    view = software_delivery_run_view()

    assert tool_run_response(view).model_dump() == {
        "summary": "Scored risk and generated cases.",
        "calls": [
            {
                "tool_name": "software_delivery.risk_score",
                "ok": True,
                "summary": "Scored risk at 62/100",
            },
            {
                "tool_name": "software_delivery.generate_test_cases",
                "ok": True,
                "summary": "Generated 2 test cases",
            },
        ],
        "risk": {
            "score": 62,
            "level": "medium",
            "rationale": (
                "Model identified moderate security concerns in the codebase"
            ),
            "factors": [
                {
                    "factor_id": "auth-surface",
                    "weight": 3,
                    "references": [
                        {"source_id": "doc-1", "source_type": "pdf"},
                        {"source_id": "SRS-2", "source_type": "srs"},
                    ],
                },
                {
                    "factor_id": "missing_acceptance_criteria",
                    "weight": 30,
                    "references": [
                        {"source_id": "US-1", "source_type": "user_story"},
                    ],
                },
            ],
        },
        "test_cases": {
            "output_style": "steps",
            "cases": [
                {
                    "title": "Lock after five failures",
                    "steps": [
                        "Sign in with a valid password.",
                        "Fail MFA five times.",
                    ],
                    "expected": "Account locked.",
                    "references": [
                        {"source_id": "US-1", "source_type": "user_story"},
                    ],
                },
                {
                    "title": "Require MFA on a new device",
                    "steps": ["Sign in from an unknown device."],
                    "expected": "MFA challenge is issued.",
                    "references": [
                        {"source_id": "AUTH-101", "source_type": "user_story"},
                    ],
                },
            ],
        },
        "markdown": "# Test Cases\n",
    }


def test_tool_run_response_projects_absent_risk_and_test_cases_as_null() -> None:
    view = SoftwareDeliveryRunView(
        summary="No tools produced structured results.",
        calls=(),
        markdown="",
    )

    assert tool_run_response(view).model_dump() == {
        "summary": "No tools produced structured results.",
        "calls": [],
        "risk": None,
        "test_cases": None,
        "markdown": "",
    }


def test_tool_run_projection_fields_are_locked() -> None:
    """Adding a field to any reachable wire model must fail this test."""
    # Import nested *Response models inside the test so pytest does not try to
    # collect TestCaseResponse / TestCasesResponse as test classes.
    from presentation.http.schemas import (
        RiskFactorResponse,
        RiskScoreResponse,
        SourceReferenceResponse,
        TestCaseResponse,
        TestCasesResponse,
    )

    expected = {
        ToolCallResponse: {"tool_name", "ok", "summary"},
        ToolRunResponse: {"summary", "calls", "risk", "test_cases", "markdown"},
        RiskScoreResponse: {"score", "level", "rationale", "factors"},
        RiskFactorResponse: {"factor_id", "weight", "references"},
        SourceReferenceResponse: {"source_id", "source_type"},
        TestCasesResponse: {"output_style", "cases"},
        TestCaseResponse: {"title", "steps", "expected", "references"},
    }

    reachable = _reachable_response_models(ToolRunResponse)
    assert reachable == set(expected)

    for model, fields in expected.items():
        assert set(model.model_fields) == fields


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
