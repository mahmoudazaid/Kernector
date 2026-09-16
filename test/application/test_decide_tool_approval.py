"""DecideToolApproval use case (#214): conflict + same-decision replay."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from application.decide_tool_approval import (
    DecideToolApproval,
    DecideToolApprovalRequest,
)
from domain.errors import ToolApprovalConflictError, ToolApprovalNotFoundError
from domain.models import AgentTurnResult
from domain.tool_approval import Decision, ToolApprovalDecisionLedger


@dataclass
class _FakeResumer:
    calls: list[tuple[str, str, Decision]]
    turn: AgentTurnResult
    raise_not_found: bool = False

    def resume_approval(
        self,
        *,
        conversation_id: str,
        approval_id: str,
        decision: Decision,
    ) -> AgentTurnResult:
        self.calls.append((conversation_id, approval_id, decision))
        if self.raise_not_found:
            raise ToolApprovalNotFoundError("No pending approval for this conversation.")
        return self.turn


def _turn(content: str = "done") -> AgentTurnResult:
    return AgentTurnResult(content=content, truncated=False)


def test_conflicting_decision_raises_without_second_resume() -> None:
    ledger = ToolApprovalDecisionLedger()
    ledger.record("a1", "approve")
    resumer = _FakeResumer(calls=[], turn=_turn())
    use_case = DecideToolApproval(resumer=resumer, ledger=ledger)

    with pytest.raises(ToolApprovalConflictError):
        use_case.execute(
            DecideToolApprovalRequest(
                conversation_id="c1",
                approval_id="a1",
                decision="reject",
            )
        )
    assert resumer.calls == []


def test_same_decision_replay_resumes_once_more_without_recording_twice() -> None:
    ledger = ToolApprovalDecisionLedger()
    resumer = _FakeResumer(calls=[], turn=_turn("exported"))
    use_case = DecideToolApproval(resumer=resumer, ledger=ledger)

    first = use_case.execute(
        DecideToolApprovalRequest(
            conversation_id="c1",
            approval_id="a1",
            decision="approve",
        )
    )
    second = use_case.execute(
        DecideToolApprovalRequest(
            conversation_id="c1",
            approval_id="a1",
            decision="approve",
        )
    )

    assert first.cancelled is False
    assert second.cancelled is False
    assert ledger.recorded("a1") == "approve"
    assert resumer.calls == [
        ("c1", "a1", "approve"),
        ("c1", "a1", "approve"),
    ]


def test_reject_sets_cancelled() -> None:
    ledger = ToolApprovalDecisionLedger()
    resumer = _FakeResumer(calls=[], turn=_turn("cancelled"))
    use_case = DecideToolApproval(resumer=resumer, ledger=ledger)

    result = use_case.execute(
        DecideToolApprovalRequest(
            conversation_id="c1",
            approval_id="a1",
            decision="reject",
        )
    )
    assert result.cancelled is True
    assert isinstance(result.turn, AgentTurnResult)


def test_not_found_rolls_back_ledger_so_owner_can_still_decide() -> None:
    ledger = ToolApprovalDecisionLedger()
    resumer = _FakeResumer(calls=[], turn=_turn(), raise_not_found=True)
    use_case = DecideToolApproval(resumer=resumer, ledger=ledger)

    with pytest.raises(ToolApprovalNotFoundError):
        use_case.execute(
            DecideToolApprovalRequest(
                conversation_id="conv-B",
                approval_id="tc-A",
                decision="approve",
            )
        )
    assert ledger.recorded("tc-A") is None
    assert resumer.calls == [("conv-B", "tc-A", "approve")]
