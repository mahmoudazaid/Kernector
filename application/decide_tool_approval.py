"""Resume a pending tool-approval interrupt (#214)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from domain.errors import ToolApprovalConflictError, ToolApprovalNotFoundError
from domain.tool_approval import Decision, ToolApprovalDecisionLedger
from domain.models import AgentTurnResult
from domain.tool_approval import PendingToolApproval


class _ApprovalResumer(Protocol):
    def resume_approval(
        self,
        *,
        conversation_id: str,
        approval_id: str,
        decision: Decision,
    ) -> AgentTurnResult: ...


@dataclass(frozen=True, slots=True)
class DecideToolApprovalRequest:
    conversation_id: str
    approval_id: str
    decision: Decision


@dataclass(frozen=True, slots=True)
class DecideToolApprovalResponse:
    turn: AgentTurnResult
    pending_approval: PendingToolApproval | None = None
    cancelled: bool = False


class DecideToolApproval:
    """Approve or reject a pending interrupt on the trusted thread."""

    def __init__(
        self,
        *,
        resumer: _ApprovalResumer,
        ledger: ToolApprovalDecisionLedger,
    ) -> None:
        self._resumer = resumer
        self._ledger = ledger

    def execute(self, request: DecideToolApprovalRequest) -> DecideToolApprovalResponse:
        conversation_id = request.conversation_id.strip()
        approval_id = request.approval_id.strip()
        if not conversation_id:
            raise ValueError("conversation_id must be a non-empty string")
        if not approval_id:
            raise ValueError("approval_id must be a non-empty string")
        if request.decision not in ("approve", "reject"):
            raise ValueError("decision must be approve or reject")

        prior = self._ledger.recorded(approval_id)
        if prior is not None:
            if prior != request.decision:
                raise ToolApprovalConflictError(
                    "This approval was already decided differently."
                )
            # Same decision replay: resume path must not invoke the Tool again.
            turn = self._resumer.resume_approval(
                conversation_id=conversation_id,
                approval_id=approval_id,
                decision=request.decision,
            )
            return DecideToolApprovalResponse(
                turn=turn,
                pending_approval=None,
                cancelled=request.decision == "reject",
            )

        self._ledger.record(approval_id, request.decision)
        try:
            turn = self._resumer.resume_approval(
                conversation_id=conversation_id,
                approval_id=approval_id,
                decision=request.decision,
            )
        except ToolApprovalNotFoundError:
            # Roll back so a cross-conversation or stale decide cannot poison
            # the real owner's later approve/reject.
            self._ledger.forget(approval_id)
            raise
        return DecideToolApprovalResponse(
            turn=turn,
            pending_approval=getattr(turn, "pending_approval", None),
            cancelled=request.decision == "reject",
        )
