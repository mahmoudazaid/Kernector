"""Pending tool-approval contracts for human-in-the-loop (#214)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

Decision = Literal["approve", "reject"]

_DEFAULT_ALLOWLIST = frozenset(
    {"software_delivery.export_test_cases_google_drive"}
)


@dataclass(frozen=True, slots=True)
class PendingToolApproval:
    """Presentation-safe pending approval; never carries raw Tool arguments."""

    approval_id: str
    tool_name: str
    title: str
    summary: str
    status: str = "pending"
    destination_label: str | None = None
    file_name: str | None = None
    selected_title_count: int | None = None

    def __post_init__(self) -> None:
        for field_name in ("approval_id", "tool_name", "title", "summary", "status"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.selected_title_count is not None:
            if (
                not isinstance(self.selected_title_count, int)
                or isinstance(self.selected_title_count, bool)
                or self.selected_title_count < 0
            ):
                raise ValueError("selected_title_count must be a non-negative int")


@dataclass(frozen=True, slots=True)
class ToolApprovalPolicy:
    """Classifies Tool names that require human approval before ``Tool.run``."""

    require_approval: frozenset[str] = _DEFAULT_ALLOWLIST

    def requires_approval(self, tool_name: str) -> bool:
        if not isinstance(tool_name, str) or not tool_name.strip():
            return False
        return tool_name.strip() in self.require_approval


@dataclass(frozen=True, slots=True)
class ApprovalHints:
    """Optional presentation hints attached beside a bound Tool."""

    title: str
    summary: str
    destination_label: str | None = None
    file_name: str | None = None
    selected_title_count: int | None = None


def project_pending_approval(
    *,
    approval_id: str,
    tool_name: str,
    arguments: Mapping[str, object],
    hints: ApprovalHints | None = None,
) -> PendingToolApproval:
    """Build a safe pending projection (no folder ids, tokens, or raw args)."""
    file_name = _optional_str(arguments.get("file_name"))
    selected_count = _title_count(arguments.get("titles"))
    if hints is not None:
        return PendingToolApproval(
            approval_id=approval_id,
            tool_name=tool_name,
            title=hints.title,
            summary=hints.summary,
            status="pending",
            destination_label=hints.destination_label,
            file_name=_optional_str(hints.file_name) or file_name,
            selected_title_count=(
                hints.selected_title_count
                if hints.selected_title_count is not None
                else selected_count
            ),
        )
    return PendingToolApproval(
        approval_id=approval_id,
        tool_name=tool_name,
        title="Approve tool action",
        summary="A high-impact tool is waiting for your approval.",
        status="pending",
        file_name=file_name,
        selected_title_count=selected_count,
    )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _title_count(value: object) -> int | None:
    if isinstance(value, list):
        return len(value)
    return None


class ToolApprovalDecisionLedger:
    """Process-local approve/reject ledger (same lifetime as InMemorySaver)."""

    def __init__(self) -> None:
        self._decisions: dict[str, Decision] = {}

    def recorded(self, approval_id: str) -> Decision | None:
        return self._decisions.get(approval_id)

    def record(self, approval_id: str, decision: Decision) -> None:
        self._decisions[approval_id] = decision

    def forget(self, approval_id: str) -> None:
        """Drop a recorded decision (e.g. when the thread is cleared)."""
        self._decisions.pop(approval_id, None)
