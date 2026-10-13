"""Text of the MCP approval prompt."""

from __future__ import annotations

from domain.tool_approval import PendingToolApproval
from presentation.mcp.app import _approval_message


def test_message_lists_destination_count_and_item_titles() -> None:
    pending = PendingToolApproval(
        "a1",
        "fake.create",
        "Create tests",
        "Creates tests.",
        destination_label="Jira project QA on jira.example.test",
        selected_title_count=2,
        item_titles=("One (a.robot:3)", "Two (a.robot:5)"),
    )

    assert _approval_message(pending).splitlines() == [
        "Create tests",
        "Creates tests.",
        "Destination: Jira project QA on jira.example.test",
        "Items: 2",
        "- One (a.robot:3)",
        "- Two (a.robot:5)",
    ]
