"""Protocol E2E: MCP elicitation approval gate for side-effect tools (ADR 0010)."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest
from mcp import Client, types
from pydantic import BaseModel, ConfigDict

from composition.mcp.access import FixedCallerContextResolver, McpCallerContext
from composition.mcp.tool_registry import (
    APPROVAL_DECLINED_CODE,
    APPROVAL_REQUIRED_CODE,
    McpToolContribution,
    McpToolRegistry,
    mcp_tool_name,
)
from domain.tool_approval import ApprovalHints, ToolApprovalPolicy
from presentation.mcp.app import build_mcp_server

SIDE_EFFECT = "fake.create_things"
READ_ONLY = "fake.read_things"
# "auto" negotiates 2026-07-28 (InputRequiredResult round trip); "legacy" uses a
# mid-call elicitation/create request.
MODES = pytest.mark.parametrize("mode", ["auto", "legacy"])


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thing_id: str


class _FakeTool:
    args_schema = _Args

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "Fake tool"
        self.runs = 0

    def approval_hints(self, arguments: Mapping[str, object]) -> ApprovalHints:
        del arguments
        return ApprovalHints(
            title="Create things",
            summary="Creates new things.",
            destination_label="QA",
            selected_title_count=2,
        )

    def run(self, arguments: Mapping[str, object]) -> str:
        del arguments
        self.runs += 1
        return json.dumps({"created": 2})


def _server(*tools: _FakeTool):
    registry = McpToolRegistry(
        contributions=tuple(
            McpToolContribution(tool.name, "fake-pack", lambda tool=tool: tool)
            for tool in tools
        ),
        enabled_packs=("fake-pack",),
        approval_policy=ToolApprovalPolicy(require_approval=frozenset({SIDE_EFFECT})),
    )
    caller = McpCallerContext("ws", "default", frozenset(tool.name for tool in tools))
    return build_mcp_server(registry=registry, resolver=FixedCallerContextResolver(caller))


class _Elicitation:
    def __init__(self, result: types.ElicitResult) -> None:
        self.result = result
        self.messages: list[str] = []

    async def __call__(self, context, params):  # noqa: ANN001
        del context
        self.messages.append(params.message)
        return self.result


def _code(result: types.CallToolResult) -> str | None:
    return json.loads(result.content[0].text).get("code")


@pytest.mark.anyio
@MODES
async def test_accepted_elicitation_runs_the_tool_once(mode: str) -> None:
    tool = _FakeTool(SIDE_EFFECT)
    elicit = _Elicitation(types.ElicitResult(action="accept", content={"approve": True}))

    async with Client(
        _server(tool), raise_exceptions=True, elicitation_callback=elicit, mode=mode
    ) as client:
        result = await client.call_tool(mcp_tool_name(SIDE_EFFECT), {"thing_id": "secret-id"})

    assert result.is_error is False
    assert tool.runs == 1
    [message] = elicit.messages
    assert "Create things" in message
    assert "QA" in message
    assert "secret-id" not in message


@pytest.mark.anyio
@MODES
@pytest.mark.parametrize(
    "answer",
    [
        types.ElicitResult(action="accept", content={"approve": False}),
        types.ElicitResult(action="decline"),
        types.ElicitResult(action="cancel"),
    ],
)
async def test_declined_or_cancelled_elicitation_never_runs_the_tool(
    mode: str, answer: types.ElicitResult
) -> None:
    tool = _FakeTool(SIDE_EFFECT)

    async with Client(
        _server(tool),
        raise_exceptions=True,
        elicitation_callback=_Elicitation(answer),
        mode=mode,
    ) as client:
        result = await client.call_tool(mcp_tool_name(SIDE_EFFECT), {"thing_id": "t"})

    assert result.is_error is True
    assert _code(result) == APPROVAL_DECLINED_CODE
    assert tool.runs == 0


@pytest.mark.anyio
@MODES
async def test_client_without_elicitation_gets_approval_required(mode: str) -> None:
    tool = _FakeTool(SIDE_EFFECT)

    async with Client(_server(tool), raise_exceptions=True, mode=mode) as client:
        result = await client.call_tool(mcp_tool_name(SIDE_EFFECT), {"thing_id": "t"})

    assert result.is_error is True
    assert _code(result) == APPROVAL_REQUIRED_CODE
    assert tool.runs == 0


@pytest.mark.anyio
@MODES
async def test_read_only_tool_never_elicits(mode: str) -> None:
    tool = _FakeTool(READ_ONLY)
    elicit = _Elicitation(types.ElicitResult(action="decline"))

    async with Client(
        _server(tool), raise_exceptions=True, elicitation_callback=elicit, mode=mode
    ) as client:
        result = await client.call_tool(mcp_tool_name(READ_ONLY), {"thing_id": "t"})

    assert result.is_error is False
    assert elicit.messages == []
    assert tool.runs == 1


@pytest.mark.anyio
async def test_unsolicited_approval_for_other_arguments_is_ignored() -> None:
    """A retry answer only counts for the exact tool call it was asked for."""
    tool = _FakeTool(SIDE_EFFECT)
    server = _server(tool)
    accepted = types.ElicitResult(action="accept", content={"approve": True})

    async with Client(server, raise_exceptions=True, elicitation_callback=_Elicitation(accepted)) as client:
        first = await client.session.send_request(
            types.CallToolRequest(
                params=types.CallToolRequestParams(
                    name=mcp_tool_name(SIDE_EFFECT),
                    arguments={"thing_id": "other"},
                    input_responses={"kernector_approval": accepted},
                    request_state="forged",
                )
            ),
            types.InputRequiredResult,
        )

    assert isinstance(first, types.InputRequiredResult)
    assert tool.runs == 0
