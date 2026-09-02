"""Tests for the pack-agnostic projected-results Streamlit seam."""

from __future__ import annotations

from pathlib import Path

import pytest

import presentation.streamlit.components as components_mod
import presentation.streamlit.tool_run_panel as panel_mod
from composition import SoftwareDeliveryRunView, ToolCallView
from presentation.streamlit.projected_results import render_projected_results


def _export_view(markdown: str = "# Test Cases\n") -> SoftwareDeliveryRunView:
    return SoftwareDeliveryRunView(
        summary="Exported.",
        calls=(
            ToolCallView(
                "software_delivery.export_test_cases_markdown",
                ok=True,
                summary="Exported test cases as Markdown",
            ),
        ),
        markdown=markdown,
    )


def test_render_projected_results_is_noop_without_a_view() -> None:
    render_projected_results(None, key_prefix="export_0")


def test_render_projected_results_accepts_export_markdown_view() -> None:
    render_projected_results(_export_view(), key_prefix="export_1")


def test_projected_results_module_delegates_to_pack_panel() -> None:
    source = Path("presentation/streamlit/projected_results.py").read_text(
        encoding="utf-8"
    )
    assert "render_software_delivery_tool_results" in source
    assert "key_prefix" in source
    assert "from packs" not in source
    assert "import packs" not in source


def test_two_historical_exports_use_distinct_download_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replaying two history turns must not collide on Streamlit download keys."""
    keys: list[str] = []

    def capture_download_button(*args: object, **kwargs: object) -> bool:
        key = kwargs.get("key")
        assert isinstance(key, str)
        keys.append(key)
        return True

    monkeypatch.setattr(components_mod.st, "download_button", capture_download_button)
    monkeypatch.setattr(panel_mod.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(panel_mod.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(
        panel_mod.st,
        "expander",
        lambda *a, **k: _NullContext(),
    )
    monkeypatch.setattr(panel_mod.st, "code", lambda *a, **k: None)

    render_projected_results(_export_view("# One\n"), key_prefix="export_1")
    render_projected_results(_export_view("# Two\n"), key_prefix="export_3")

    assert keys == ["download_export_1", "download_export_3"]
    assert len(set(keys)) == 2


def test_history_plus_live_exports_use_distinct_download_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """History replay plus a live turn must keep three distinct export keys."""
    keys: list[str] = []

    def capture_download_button(*args: object, **kwargs: object) -> bool:
        key = kwargs.get("key")
        assert isinstance(key, str)
        keys.append(key)
        return True

    monkeypatch.setattr(components_mod.st, "download_button", capture_download_button)
    monkeypatch.setattr(panel_mod.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(panel_mod.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(
        panel_mod.st,
        "expander",
        lambda *a, **k: _NullContext(),
    )
    monkeypatch.setattr(panel_mod.st, "code", lambda *a, **k: None)

    # History indices 1 and 3, then live pending assistant index 5
    render_projected_results(_export_view("# Hist A\n"), key_prefix="export_1")
    render_projected_results(_export_view("# Hist B\n"), key_prefix="export_3")
    render_projected_results(_export_view("# Live\n"), key_prefix="export_5")

    assert keys == [
        "download_export_1",
        "download_export_3",
        "download_export_5",
    ]
    assert len(set(keys)) == 3


class _NullContext:
    def __enter__(self) -> "_NullContext":
        return self

    def __exit__(self, *args: object) -> None:
        return None
