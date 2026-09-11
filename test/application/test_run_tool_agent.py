"""Tests for RunToolAgent validation and delegation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from application.errors import ApplicationValidationError
from application.run_tool_agent import RunToolAgent
from domain.models import AgentTurnResult
from domain.ports import Tool


class _FakeAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...], int]] = []

    def run(
        self,
        goal: str,
        tools: Sequence[Tool],
        *,
        max_steps: int,
    ) -> AgentTurnResult:
        self.calls.append((goal, tuple(t.name for t in tools), max_steps))
        return AgentTurnResult(content="done", steps=1)


class _Tool:
    @property
    def name(self) -> str:
        return "t"

    @property
    def description(self) -> str:
        return "tool"

    def run(self, arguments: Mapping[str, object]) -> str:
        return "ok"


def test_run_tool_agent_delegates_to_port() -> None:
    agent = _FakeAgent()
    use_case = RunToolAgent(agent)

    result = use_case.execute("goal text", [_Tool()], max_steps=4)

    assert result == AgentTurnResult(content="done", steps=1)
    assert agent.calls == [("goal text", ("t",), 4)]


def test_run_tool_agent_rejects_blank_goal() -> None:
    with pytest.raises(ApplicationValidationError, match="goal"):
        RunToolAgent(_FakeAgent()).execute("  ", [_Tool()], max_steps=1)


def test_run_tool_agent_rejects_non_positive_max_steps() -> None:
    with pytest.raises(ApplicationValidationError, match="max_steps"):
        RunToolAgent(_FakeAgent()).execute("goal", [_Tool()], max_steps=0)
