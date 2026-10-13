"""Kernector exposes no MCP resources, but clients that probe for them get empty lists."""

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client
from mcp.server.lowlevel import Server

from composition.mcp.access import FixedCallerContextResolver, McpCallerContext
from composition.mcp.tool_registry import McpToolRegistry
from presentation.mcp.app import build_mcp_server


def _server() -> Server[Any]:
    caller = McpCallerContext(workspace_id="ws-test", profile_id="default", allowlist=frozenset())
    return build_mcp_server(
        registry=McpToolRegistry(contributions=(), enabled_packs=()),
        resolver=FixedCallerContextResolver(caller),
    )


@pytest.mark.anyio
async def test_list_resources_is_empty_not_method_not_found() -> None:
    async with Client(_server(), raise_exceptions=True) as client:
        result = await client.list_resources()
    assert result.resources == []


@pytest.mark.anyio
async def test_list_resource_templates_is_empty_not_method_not_found() -> None:
    async with Client(_server(), raise_exceptions=True) as client:
        result = await client.list_resource_templates()
    assert result.resource_templates == []
