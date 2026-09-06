"""Behavior tests for the generic tool-call envelope."""

from __future__ import annotations

import dataclasses
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import composition
import composition.tool_runs as tool_runs_mod
from application.contracts import InvokeToolResponse
from composition.software_delivery_chat import (
    ToolRunFailedError,
    project_software_delivery_run_view,
)
from composition.tool_runs import MAX_TOOL_CALL_SUMMARY_CHARS, ToolCallView


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


def test_unrecognised_outcome_keeps_opaque_tool_outputs() -> None:
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
    assert excinfo.value.tool_outputs == tool_outputs


def test_fresh_tool_runs_module_has_no_summary_projection_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "composition.tool_runs", raising=False)
    fresh = importlib.import_module("composition.tool_runs")

    assert not hasattr(fresh, "bounded_tool_call_summary")
    assert hasattr(fresh, "MAX_TOOL_CALL_SUMMARY_CHARS")
    assert hasattr(fresh, "ToolCallView")
