"""Generic MCP side-effect approval in the shared registry (ADR 0010, #199)."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest
from pydantic import BaseModel, ConfigDict

from composition.mcp.access import McpCallerContext
from composition.mcp.tool_registry import (
    APPROVAL_DECLINED_CODE,
    APPROVAL_REQUIRED_CODE,
    TOOL_UNAVAILABLE_CODE,
    VALIDATION_ERROR_CODE,
    McpToolContribution,
    McpToolRegistry,
)
from domain.errors import ToolTargetNotFoundError
from domain.tool_approval import ApprovalHints, PendingToolApproval, ToolApprovalPolicy

SIDE_EFFECT = "fake.create_things"
READ_ONLY = "fake.read_things"
POLICY = ToolApprovalPolicy(require_approval=frozenset({SIDE_EFFECT}))


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thing_id: str


class _FakeTool:
    args_schema = _Args

    def __init__(self, name: str, *, hints_error: Exception | None = None) -> None:
        self.name = name
        self.description = "Fake tool"
        self.runs: list[Mapping[str, object]] = []
        self.hint_calls: list[Mapping[str, object]] = []
        self._hints_error = hints_error

    def approval_hints(self, arguments: Mapping[str, object]) -> ApprovalHints:
        self.hint_calls.append(dict(arguments))
        if self._hints_error is not None:
            raise self._hints_error
        return ApprovalHints(
            title="Create things",
            summary="Creates new things.",
            destination_label="QA",
            selected_title_count=3,
        )

    def run(self, arguments: Mapping[str, object]) -> str:
        self.runs.append(dict(arguments))
        return json.dumps({"ok": True})


class _UnhintedTool(_FakeTool):
    approval_hints = None  # type: ignore[assignment]


class _Gate:
    def __init__(self, answer: bool | Exception) -> None:
        self.answer = answer
        self.requests: list[PendingToolApproval] = []

    def __call__(self, request: PendingToolApproval) -> bool:
        self.requests.append(request)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _registry(tool: _FakeTool, policy: ToolApprovalPolicy = POLICY) -> McpToolRegistry:
    return McpToolRegistry(
        contributions=(McpToolContribution(tool.name, "fake-pack", lambda: tool),),
        enabled_packs=("fake-pack",),
        approval_policy=policy,
    )


def _caller(*tool_ids: str) -> McpCallerContext:
    return McpCallerContext("ws", "default", frozenset(tool_ids))


def test_side_effect_tool_without_a_gate_fails_closed() -> None:
    tool = _FakeTool(SIDE_EFFECT)

    result = _registry(tool).invoke_authorized(_caller(SIDE_EFFECT), SIDE_EFFECT, {"thing_id": "t"})

    assert result.is_error and result.code == APPROVAL_REQUIRED_CODE
    assert tool.runs == []


def test_declined_approval_never_runs_the_tool() -> None:
    tool = _FakeTool(SIDE_EFFECT)
    gate = _Gate(False)

    result = _registry(tool).invoke_authorized(
        _caller(SIDE_EFFECT), SIDE_EFFECT, {"thing_id": "secret-id"}, approve=gate
    )

    assert result.is_error and result.code == APPROVAL_DECLINED_CODE
    assert tool.runs == []
    [request] = gate.requests
    assert (request.tool_name, request.title, request.destination_label) == (
        SIDE_EFFECT,
        "Create things",
        "QA",
    )
    assert request.selected_title_count == 3
    assert "secret-id" not in repr(request)
    assert "secret-id" not in result.text


def test_approved_call_runs_the_tool_once() -> None:
    tool = _FakeTool(SIDE_EFFECT)

    result = _registry(tool).invoke_authorized(
        _caller(SIDE_EFFECT), SIDE_EFFECT, {"thing_id": "t"}, approve=_Gate(True)
    )

    assert not result.is_error
    assert tool.runs == [{"thing_id": "t"}]


def test_a_failing_gate_fails_closed() -> None:
    tool = _FakeTool(SIDE_EFFECT)

    result = _registry(tool).invoke_authorized(
        _caller(SIDE_EFFECT),
        SIDE_EFFECT,
        {"thing_id": "t"},
        approve=_Gate(RuntimeError("no back channel")),
    )

    assert result.code == APPROVAL_REQUIRED_CODE
    assert "back channel" not in result.text
    assert tool.runs == []


def test_unauthorized_caller_is_unavailable_before_any_approval_work() -> None:
    tool = _FakeTool(SIDE_EFFECT)
    gate = _Gate(True)

    result = _registry(tool).invoke_authorized(
        _caller(), SIDE_EFFECT, {"thing_id": "t"}, approve=gate
    )

    assert result.code == TOOL_UNAVAILABLE_CODE
    assert (tool.hint_calls, gate.requests, tool.runs) == ([], [], [])


def test_invalid_arguments_fail_validation_before_the_gate() -> None:
    tool = _FakeTool(SIDE_EFFECT)
    gate = _Gate(True)

    result = _registry(tool).invoke_authorized(
        _caller(SIDE_EFFECT), SIDE_EFFECT, {"other": "x"}, approve=gate
    )

    assert result.code == VALIDATION_ERROR_CODE
    assert (tool.hint_calls, gate.requests, tool.runs) == ([], [], [])


def test_hint_failures_use_safe_codes_and_skip_the_gate() -> None:
    tool = _FakeTool(SIDE_EFFECT, hints_error=ToolTargetNotFoundError("missing"))
    gate = _Gate(True)

    result = _registry(tool).invoke_authorized(
        _caller(SIDE_EFFECT), SIDE_EFFECT, {"thing_id": "t"}, approve=gate
    )

    assert result.code == "not_found"
    assert (gate.requests, tool.runs) == ([], [])


def test_tools_without_hints_get_the_generic_projection() -> None:
    tool = _UnhintedTool(SIDE_EFFECT)
    gate = _Gate(False)

    _registry(tool).invoke_authorized(
        _caller(SIDE_EFFECT), SIDE_EFFECT, {"thing_id": "t"}, approve=gate
    )

    [request] = gate.requests
    assert request.title == "Approve tool action"


def test_read_only_tool_never_invokes_the_approval_projector_or_gate() -> None:
    tool = _FakeTool(READ_ONLY, hints_error=AssertionError("projector must not run"))
    gate = _Gate(AssertionError("gate must not run"))

    result = _registry(tool).invoke_authorized(
        _caller(READ_ONLY), READ_ONLY, {"thing_id": "t"}, approve=gate
    )

    assert not result.is_error
    assert tool.hint_calls == []
    assert gate.requests == []
    assert tool.runs == [{"thing_id": "t"}]


@pytest.mark.parametrize("approve", [None, _Gate(False)])
def test_read_only_tool_runs_with_or_without_a_gate(approve: _Gate | None) -> None:
    tool = _FakeTool(READ_ONLY)

    result = _registry(tool).invoke_authorized(
        _caller(READ_ONLY), READ_ONLY, {"thing_id": "t"}, approve=approve
    )

    assert not result.is_error


def test_registry_defaults_to_the_chat_approval_policy() -> None:
    tool = _FakeTool("software_delivery.create_xray_tests")
    registry = McpToolRegistry(
        contributions=(McpToolContribution(tool.name, "fake-pack", lambda: tool),),
        enabled_packs=("fake-pack",),
    )

    result = registry.invoke_authorized(_caller(tool.name), tool.name, {"thing_id": "t"})

    assert result.code == APPROVAL_REQUIRED_CODE
    assert tool.runs == []
