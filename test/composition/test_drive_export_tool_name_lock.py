"""Guard: composition/domain Drive tool-name copies stay locked to the pack."""

from __future__ import annotations

from composition import prepare_drive_export, software_delivery_agent
from domain.tool_approval import ToolApprovalPolicy
from packs.software_delivery.tools.export_test_cases_google_drive import TOOL_NAME


def test_drive_export_tool_name_copies_match_pack_source_of_truth() -> None:
    assert prepare_drive_export.TOOL_NAME == TOOL_NAME
    assert software_delivery_agent.TOOL_NAME == TOOL_NAME
    assert ToolApprovalPolicy().requires_approval(TOOL_NAME) is True
