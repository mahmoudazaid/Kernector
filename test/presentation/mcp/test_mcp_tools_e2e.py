"""Protocol E2E: core.search_knowledge and MCP deny paths (no scaffolding tools)."""

from __future__ import annotations

import json

import pytest
from mcp import Client

from application.contracts import RetrieveRequest, RetrieveResponse
from composition.mcp_access import FixedCallerContextResolver, McpCallerContext
from composition.mcp_search_knowledge import TOOL_NAME as SEARCH_TOOL
from composition.mcp_search_knowledge import SearchKnowledgeTool
from composition.mcp_tool_registry import (
    TOOL_UNAVAILABLE_CODE,
    McpToolContribution,
    McpToolRegistry,
)
from domain.knowledge import DocumentChunk, ScoredChunk, SourceMetadata, SourceReference
from presentation.mcp.app import build_mcp_server


def _hit(source_id: str, content: str) -> ScoredChunk:
    ref = SourceReference(source_id, "doc")
    return ScoredChunk(
        chunk=DocumentChunk(
            metadata=SourceMetadata(reference=ref, title="t"),
            index=0,
            content=content,
        ),
        score=0.8,
    )


class _StubRetrieve:
    def execute(self, request: RetrieveRequest) -> RetrieveResponse:
        return RetrieveResponse(hits=(_hit("doc-1", "bounded evidence text"),))


def _registry_core_only() -> McpToolRegistry:
    return McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id=SEARCH_TOOL,
                pack_id=None,
                factory=lambda: SearchKnowledgeTool(_StubRetrieve()),
            ),
        ),
        enabled_packs=("software-delivery",),
    )


@pytest.mark.anyio
async def test_search_knowledge_e2e_via_protocol_client() -> None:
    registry = _registry_core_only()
    caller = McpCallerContext("ws", "default", frozenset({SEARCH_TOOL}))
    server = build_mcp_server(
        registry=registry, resolver=FixedCallerContextResolver(caller)
    )
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        names = [tool.name for tool in listed.tools]
        assert names == [SEARCH_TOOL]
        tool = listed.tools[0]
        assert "evidence" in (tool.description or "").lower()
        assert tool.input_schema is not None
        result = await client.call_tool(
            SEARCH_TOOL, {"query": "restart service", "retrieval_limit": 3}
        )
        assert result.is_error is False
        payload = json.loads(result.content[0].text)
        assert payload["evidence"][0]["content"] == "bounded evidence text"
        assert payload["citations"][0]["source"]["source_id"] == "doc-1"


@pytest.mark.anyio
async def test_identical_tool_unavailable_matrix() -> None:
    registry = _registry_core_only()
    caller = McpCallerContext(
        "ws",
        "default",
        frozenset(
            {
                SEARCH_TOOL,
                "software_delivery.risk_score",  # retired scaffolding; not contributed
                "software_delivery.export_test_cases_google_drive",
            }
        ),
    )
    server = build_mcp_server(
        registry=registry, resolver=FixedCallerContextResolver(caller)
    )
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        assert [t.name for t in listed.tools] == [SEARCH_TOOL]
        results = []
        for name in (
            "nope.tool",
            "software_delivery.risk_score",
            "software_delivery.generate_test_cases",
            "software_delivery.export_test_cases_markdown",
            "software_delivery.export_test_cases_google_drive",
        ):
            result = await client.call_tool(name, {})
            assert result.is_error is True
            payload = json.loads(result.content[0].text)
            results.append(payload)
        assert all(item["code"] == TOOL_UNAVAILABLE_CODE for item in results)
        assert len({json.dumps(item, sort_keys=True) for item in results}) == 1


def test_chat_build_tools_remains_drive_only() -> None:
    from packs.software_delivery.registration import build_mcp_tools, build_tools

    assert build_tools() == ()
    assert build_mcp_tools() == ()
