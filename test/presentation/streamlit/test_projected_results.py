"""Tests for the pack-agnostic projected-results Streamlit seam."""

from __future__ import annotations

from pathlib import Path

from composition import SoftwareDeliveryRunView, ToolCallView
from presentation.streamlit.projected_results import render_projected_results


def test_render_projected_results_is_noop_without_a_view() -> None:
    render_projected_results(None)


def test_render_projected_results_accepts_export_markdown_view() -> None:
    view = SoftwareDeliveryRunView(
        summary="Exported.",
        calls=(
            ToolCallView(
                "software_delivery.export_test_cases_markdown",
                ok=True,
                summary="Exported test cases as Markdown",
            ),
        ),
        markdown="# Test Cases\n",
    )
    render_projected_results(view)


def test_projected_results_module_delegates_to_pack_panel() -> None:
    source = Path("presentation/streamlit/projected_results.py").read_text(
        encoding="utf-8"
    )
    assert "render_software_delivery_tool_results" in source
    assert "from packs" not in source
    assert "import packs" not in source
