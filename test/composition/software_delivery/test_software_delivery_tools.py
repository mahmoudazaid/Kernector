"""Behavior tests for Software Delivery composition views."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from composition.software_delivery.tools import (
    SoftwareDeliveryRunView,
    software_delivery_tools_enabled,
)
from composition.tools.runs import ToolCallView


class _Settings:
    """Duck-typed stand-in: reads ``domain_tools.enabled_packs`` only."""

    def __init__(self, *packs: str) -> None:
        self.domain_tools = SimpleNamespace(enabled_packs=packs)


def _fixture_view() -> SoftwareDeliveryRunView:
    return SoftwareDeliveryRunView(
        summary="Export finished.",
        calls=(
            ToolCallView(
                "software_delivery.export_test_cases_google_drive",
                ok=True,
                summary="Exported test cases to Google Drive",
            ),
        ),
        drive_file_id="file-1",
        drive_file_name="test-cases.md",
        drive_destination_label="My Drive",
    )


def test_fixture_view_carries_the_drive_receipt() -> None:
    view = _fixture_view()

    assert view.drive_file_name == "test-cases.md"
    assert view.drive_destination_label == "My Drive"
    assert all(isinstance(call, ToolCallView) for call in view.calls)
    assert all(not hasattr(call, "result") for call in view.calls)


def test_tool_renderers_are_absent_when_the_pack_is_disabled() -> None:
    assert software_delivery_tools_enabled(_Settings()) is False
    assert software_delivery_tools_enabled(_Settings("other-pack")) is False


def test_tool_renderers_may_be_shown_when_the_pack_is_enabled() -> None:
    assert software_delivery_tools_enabled(_Settings("software-delivery")) is True


def test_software_delivery_tools_module_stays_view_only() -> None:
    source = Path("composition/software_delivery/tools.py").read_text(encoding="utf-8")
    assert "import packs" not in source
    assert "from packs" not in source
    assert "retrieve" not in source.lower() or "no retrieval" in source.lower()
    assert "PackSoftwareDeliveryTools" not in source
    assert "run_view" not in source
