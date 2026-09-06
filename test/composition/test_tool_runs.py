"""Behavior tests for the generic tool-call envelope."""

from __future__ import annotations

import dataclasses
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args, get_origin

import pytest
from pydantic import BaseModel

import composition
import composition.tool_runs as tool_runs_mod
from application.contracts import InvokeToolResponse
from composition.software_delivery_chat import (
    ToolRunFailedError,
    project_software_delivery_run_view,
)
from composition.software_delivery_tools import (
    RiskFactorView,
    RiskScoreView,
    SoftwareDeliveryRunView,
    TestCaseView,
    TestCasesView,
)
from composition.tool_runs import MAX_TOOL_CALL_SUMMARY_CHARS, ToolCallView
from domain.knowledge import SourceReference
from presentation.http.schemas import (
    ToolCallResponse,
    ToolRunResponse,
    tool_run_response,
    tools_used_response,
)


def test_tool_call_view_fields_are_name_status_and_summary_only() -> None:
    fields = {field.name for field in dataclasses.fields(ToolCallView)}

    assert fields == {"tool_name", "ok", "summary"}
    assert "result" not in fields


def test_tool_call_view_accepts_explicitly_authored_summary() -> None:
    view = ToolCallView(
        "software_delivery.risk_score",
        ok=True,
        summary="Scored risk at 62/100",
    )

    assert view.tool_name == "software_delivery.risk_score"
    assert view.ok is True
    assert view.summary == "Scored risk at 62/100"


def test_tool_call_view_rejects_summaries_longer_than_the_limit() -> None:
    with pytest.raises(ValueError, match="summary must be at most"):
        ToolCallView("tool", ok=True, summary="x" * (MAX_TOOL_CALL_SUMMARY_CHARS + 1))


def test_composition_exports_no_raw_to_summary_helper() -> None:
    assert not hasattr(composition, "bounded_tool_call_summary")

    source = Path(tool_runs_mod.__file__).read_text(encoding="utf-8")
    assert "def bounded_tool_call_summary" not in source
    assert "def bounded_" not in source


def test_tool_run_response_projects_a_typed_view() -> None:
    view = SoftwareDeliveryRunView(
        summary="Scored risk and generated cases.",
        calls=(
            ToolCallView(
                "software_delivery.risk_score",
                ok=True,
                summary="Scored risk at 62/100",
            ),
            ToolCallView(
                "software_delivery.generate_test_cases",
                ok=True,
                summary="Generated 1 test case",
            ),
        ),
        risk=RiskScoreView(
            score=62,
            level="medium",
            rationale="Model identified moderate security concerns in the codebase",
            factors=(
                RiskFactorView(
                    factor_id="auth-surface",
                    weight=3,
                    references=(
                        SourceReference("doc-1", "pdf"),
                        SourceReference("SRS-2", "srs"),
                    ),
                ),
            ),
        ),
        test_cases=TestCasesView(
            output_style="steps",
            cases=(
                TestCaseView(
                    title="Lock after five failures",
                    steps=(
                        "Sign in with a valid password.",
                        "Fail MFA five times.",
                    ),
                    expected="Account locked.",
                    references=(SourceReference("US-1", "user_story"),),
                ),
            ),
        ),
        markdown="# Test Cases\n",
    )

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
                "summary": "Generated 1 test case",
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
            ],
        },
        "markdown": "# Test Cases\n",
    }


def test_opaque_tool_result_payloads_never_reach_the_wire() -> None:
    tool_outputs = (
        InvokeToolResponse(
            "software_delivery.risk_score",
            '{"score": 62, "api_key": "sk-live-abc"}',
        ),
        InvokeToolResponse(
            "software_delivery.generate_test_cases",
            '{"score": 62, "secret_token": "sk-live-abc"}',
        ),
    )
    response = SimpleNamespace(
        summary="Ran something new.",
        outcomes=(object(),),
    )

    with pytest.raises(ToolRunFailedError) as excinfo:
        project_software_delivery_run_view(response, tool_outputs=tool_outputs)

    assert str(excinfo.value) == "The tool run produced an unrecognised result."
    assert "sk-live-abc" not in str(excinfo.value)
    assert excinfo.value.tool_outputs == tool_outputs

    projected = tools_used_response(excinfo.value.tool_outputs)
    rendered = [item.model_dump_json() for item in projected]
    for output in tool_outputs:
        assert all(output.result not in payload for payload in rendered)
    assert all("sk-live-abc" not in payload for payload in rendered)
    assert all(
        set(item.model_dump()) == {"tool_name", "result_chars"} for item in projected
    )


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

    reachable = _reachable_response_models(ToolRunResponse) | {ToolCallResponse}
    assert reachable == set(expected)

    for model, fields in expected.items():
        assert set(model.model_fields) == fields


def test_fresh_tool_runs_module_has_no_summary_projection_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "composition.tool_runs", raising=False)
    fresh = importlib.import_module("composition.tool_runs")

    assert not hasattr(fresh, "bounded_tool_call_summary")
    assert hasattr(fresh, "MAX_TOOL_CALL_SUMMARY_CHARS")
    assert hasattr(fresh, "ToolCallView")


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
