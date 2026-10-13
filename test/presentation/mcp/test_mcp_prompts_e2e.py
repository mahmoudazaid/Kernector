"""Protocol E2E: server instructions and tool-contributed prompts."""

from __future__ import annotations

import pytest
from mcp import Client, MCPError

from composition.mcp.access import FixedCallerContextResolver, McpCallerContext
from composition.mcp.tool_registry import McpToolContribution, McpToolRegistry, mcp_tool_name
from composition.xray_export.test_file_preview import (
    PREVIEW_PROMPT_NAME,
    TestFilePreviewMcpBinding,
)
from packs.software_delivery.registration import build_mcp_tools
from packs.software_delivery.test_files.models import TestFileTagConfig
from packs.software_delivery.tools.preview_test_file_scenarios import TOOL_NAME
from presentation.mcp.app import build_mcp_server


def _server(*allowed: str):  # noqa: ANN202
    binding = TestFilePreviewMcpBinding(TestFileTagConfig("XRay", "Story", ("manual",)))
    registry = McpToolRegistry(
        contributions=tuple(
            McpToolContribution(tool_id, "software-delivery", factory)
            for tool_id, factory in build_mcp_tools(test_file_binding=binding)
        ),
        enabled_packs=("software-delivery",),
    )
    caller = McpCallerContext("ws", "default", frozenset(allowed))
    return build_mcp_server(registry=registry, resolver=FixedCallerContextResolver(caller))


@pytest.mark.anyio
async def test_server_instructions_tell_clients_to_send_file_text_themselves() -> None:
    async with Client(_server(), raise_exceptions=True) as client:
        instructions = client.instructions or ""

    assert "never reads your workspace" in instructions
    assert TOOL_NAME not in instructions and mcp_tool_name(TOOL_NAME) not in instructions


@pytest.mark.anyio
async def test_allowed_caller_lists_and_renders_the_preview_prompt() -> None:
    async with Client(_server(TOOL_NAME), raise_exceptions=True) as client:
        [prompt] = (await client.list_prompts()).prompts
        result = await client.get_prompt(PREVIEW_PROMPT_NAME, {"file": "f/login.feature"})

    assert prompt.name == PREVIEW_PROMPT_NAME
    assert [(item.name, item.required) for item in prompt.arguments or ()] == [("file", False)]
    [message] = result.messages
    assert message.role == "user"
    assert mcp_tool_name(TOOL_NAME) in message.content.text  # type: ignore[union-attr]
    assert "`f/login.feature`" in message.content.text  # type: ignore[union-attr]


@pytest.mark.anyio
async def test_prompt_is_hidden_and_unknown_without_the_tool() -> None:
    async with Client(_server(), raise_exceptions=True) as client:
        listed = await client.list_prompts()
        with pytest.raises(MCPError, match="Unknown prompt"):
            await client.get_prompt(PREVIEW_PROMPT_NAME)

    assert listed.prompts == []


@pytest.mark.anyio
async def test_invalid_prompt_argument_is_rejected_with_a_fixed_message() -> None:
    async with Client(_server(TOOL_NAME), raise_exceptions=True) as client:
        with pytest.raises(MCPError, match="Invalid prompt arguments"):
            await client.get_prompt(PREVIEW_PROMPT_NAME, {"file": "a\x00.feature"})
