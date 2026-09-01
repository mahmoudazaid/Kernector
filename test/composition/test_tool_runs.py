"""Behavior tests for the generic tool-call envelope."""

from __future__ import annotations

import dataclasses
import importlib
import sys
from pathlib import Path

import pytest

import composition
import composition.tool_runs as tool_runs_mod
from composition.tool_runs import MAX_TOOL_CALL_SUMMARY_CHARS, ToolCallView
from presentation.streamlit.tool_run import tool_call_lines


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


def test_rendered_tool_call_lines_never_include_raw_payload_secrets() -> None:
    calls = (
        ToolCallView(
            "software_delivery.risk_score",
            ok=True,
            summary="Scored risk at 62/100",
        ),
        ToolCallView("software_delivery.generate_test_cases", ok=False),
    )

    rendered = " ".join(tool_call_lines(calls))

    assert "sk-live-abc" not in rendered
    assert '{"score"' not in rendered


def test_fresh_tool_runs_module_has_no_summary_projection_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "composition.tool_runs", raising=False)
    fresh = importlib.import_module("composition.tool_runs")

    assert not hasattr(fresh, "bounded_tool_call_summary")
    assert hasattr(fresh, "MAX_TOOL_CALL_SUMMARY_CHARS")
    assert hasattr(fresh, "ToolCallView")
