"""Guard: composition/domain Xray tool-name copies stay locked to the pack (#199)."""

from __future__ import annotations

from composition.software_delivery import agent as software_delivery_agent
from composition.xray_export import prepare as prepare_xray_export
from domain.tool_approval import ToolApprovalPolicy
from packs.software_delivery.tools.create_xray_tests import TOOL_NAME


def test_xray_tool_name_copies_match_pack_source_of_truth() -> None:
    assert prepare_xray_export.TOOL_NAME == TOOL_NAME
    assert software_delivery_agent.XRAY_TOOL_NAME == TOOL_NAME


def test_xray_tool_requires_approval_by_default() -> None:
    assert ToolApprovalPolicy().requires_approval(TOOL_NAME) is True
