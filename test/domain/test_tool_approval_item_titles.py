"""Approval prompts can list the items a tool call will act on."""

from __future__ import annotations

import pytest

from domain.tool_approval import ApprovalHints, PendingToolApproval, project_pending_approval


def test_hint_item_titles_reach_the_pending_projection() -> None:
    pending = project_pending_approval(
        approval_id="a1",
        tool_name="fake.create",
        arguments={},
        hints=ApprovalHints("Create", "Creates things.", item_titles=("One", "Two")),
    )

    assert pending.item_titles == ("One", "Two")


def test_item_titles_default_to_none_listed() -> None:
    assert PendingToolApproval("a1", "fake.create", "Create", "Creates.").item_titles == ()


@pytest.mark.parametrize("titles", [("ok", 1), ("ok", " ")])
def test_item_titles_must_be_non_blank_strings(titles: tuple[object, ...]) -> None:
    with pytest.raises(ValueError, match="item_titles"):
        PendingToolApproval("a1", "fake.create", "Create", "Creates.", item_titles=titles)  # type: ignore[arg-type]
