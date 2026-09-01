"""Behavior tests for the generic tool-call envelope."""

from __future__ import annotations

import pytest

from composition.tool_runs import (
    MAX_TOOL_CALL_SUMMARY_CHARS,
    ToolCallView,
    bounded_tool_call_summary,
)


def test_tool_call_view_carries_name_status_and_bounded_summary_only() -> None:
    view = ToolCallView(
        "software_delivery.risk_score",
        ok=True,
        summary="Scored risk at 62/100",
    )

    assert view.tool_name == "software_delivery.risk_score"
    assert view.ok is True
    assert view.summary == "Scored risk at 62/100"
    assert not hasattr(view, "result")


def test_tool_call_view_rejects_summaries_longer_than_the_limit() -> None:
    with pytest.raises(ValueError, match="summary must be at most"):
        ToolCallView("tool", ok=True, summary="x" * (MAX_TOOL_CALL_SUMMARY_CHARS + 1))


def test_bounded_tool_call_summary_truncates_without_exposing_payloads() -> None:
    raw = '{"score":62,"secret":"sk-live-abc","factors":[...]}' * 5

    summary = bounded_tool_call_summary(raw)

    assert len(summary) <= MAX_TOOL_CALL_SUMMARY_CHARS
    assert "sk-live-abc" not in summary or len(summary) < len(raw.strip())
    assert summary.endswith("…")


def test_bounded_tool_call_summary_leaves_short_text_unchanged() -> None:
    assert bounded_tool_call_summary("  ok  ") == "ok"
