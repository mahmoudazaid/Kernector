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


_TEST_DESIGN_TOOLS = frozenset(
    {
        "software_delivery.test_design_start",
        "software_delivery.test_design_get",
        "software_delivery.test_design_confirm",
        "software_delivery.test_design_generate",
    }
)


def _wired_registry(tmp_path, monkeypatch: pytest.MonkeyPatch, *, pack_on: bool = True):
    import composition.container as container
    from composition.mcp_wiring import build_mcp_tool_registry
    from test.composition.test_design_fakes import build_fake_facade, settings_with_pack

    settings = settings_with_pack(pack_on=pack_on, workspace_id="ws-a")
    monkeypatch.setattr(
        container,
        "build_test_design_facade",
        lambda _settings: build_fake_facade(tmp_path, workspace_id="ws-a"),
    )
    return build_mcp_tool_registry(settings, retrieve=_StubRetrieve())


async def _call(client, name: str, arguments: dict) -> dict:
    result = await client.call_tool(name, arguments)
    assert result.is_error is False, result.content[0].text
    return json.loads(result.content[0].text)


@pytest.mark.anyio
async def test_test_design_workflow_e2e_via_protocol_client(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test.composition.test_design_fakes import ISSUE_LOCATOR

    registry = _wired_registry(tmp_path, monkeypatch)
    caller = McpCallerContext("ws-a", "default", _TEST_DESIGN_TOOLS)
    server = build_mcp_server(
        registry=registry, resolver=FixedCallerContextResolver(caller)
    )
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        assert {tool.name for tool in listed.tools} == _TEST_DESIGN_TOOLS
        for tool in listed.tools:
            assert "workspace_id" not in json.dumps(tool.input_schema)
            assert "workspace_id" not in json.dumps(tool.output_schema)

        started = await _call(
            client,
            "software_delivery.test_design_start",
            {"issue_locator": ISSUE_LOCATOR},
        )
        assert started["status"] == "coverage_review"
        assert started["version"] == 1
        assert started["ticket_identifier"] == ISSUE_LOCATOR
        assert all(c["untrusted_model_output"] for c in started["candidates"])
        draft_id = started["draft_id"]

        fetched = await _call(
            client, "software_delivery.test_design_get", {"draft_id": draft_id}
        )
        assert fetched["version"] == 1
        assert fetched["candidates"] == started["candidates"]

        confirmed = await _call(
            client,
            "software_delivery.test_design_confirm",
            {
                "draft_id": draft_id,
                "expected_version": 1,
                "candidate_ids": ["cand-1", "cand-2"],
            },
        )
        assert confirmed["status"] == "ready"
        assert confirmed["version"] == 3
        assert confirmed["selected_candidate_ids"] == ["cand-1", "cand-2"]

        generated = await _call(
            client,
            "software_delivery.test_design_generate",
            {
                "draft_id": draft_id,
                "expected_version": 3,
                "type_overrides": [
                    {"candidate_id": "cand-1", "test_type": "manual"},
                    {"candidate_id": "cand-2", "test_type": "cucumber"},
                ],
            },
        )
        assert generated["status"] == "case_editing"
        assert generated["version"] == 4
        cases = {case["candidate_id"]: case for case in generated["generated_cases"]}
        assert cases["cand-1"]["test_type"] == "manual"
        assert cases["cand-1"]["steps"] == [
            "Open the login page",
            "Submit valid credentials",
        ]
        assert cases["cand-1"]["expected_result"] == "The dashboard is shown"
        assert cases["cand-1"]["gherkin"] == ""
        assert cases["cand-2"]["test_type"] == "cucumber"
        assert cases["cand-2"]["steps"] == []
        assert cases["cand-2"]["gherkin"].startswith("Given a locked account")
        assert all(case["untrusted_model_output"] for case in cases.values())
        assert generated["cucumber"] == {
            "feature": "Login",
            "background": "Given the login page is open",
            "untrusted_model_output": True,
        }

        final = await _call(
            client, "software_delivery.test_design_get", {"draft_id": draft_id}
        )
        assert final["version"] == 4
        assert final["generated_cases"] == generated["generated_cases"]

        stale = await client.call_tool(
            "software_delivery.test_design_confirm",
            {"draft_id": draft_id, "expected_version": 1, "candidate_ids": ["cand-1"]},
        )
        assert stale.is_error is True
        assert json.loads(stale.content[0].text)["code"] == "version_conflict"

        rejected = await client.call_tool(
            "software_delivery.test_design_get",
            {"draft_id": draft_id, "workspace_id": "ws-b"},
        )
        assert rejected.is_error is True
        assert json.loads(rejected.content[0].text)["code"] == "validation_error"


class _UnauthorizedResolver:
    def resolve(self, request: object | None) -> McpCallerContext:
        from composition.mcp_access import MissingCallerContextError

        raise MissingCallerContextError("missing authenticated caller context")


async def _deny_payload(server) -> tuple[list[str], str]:
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        result = await client.call_tool(
            "software_delivery.test_design_get", {"draft_id": "d"}
        )
        assert result.is_error is True
        return [tool.name for tool in listed.tools], result.content[0].text


@pytest.mark.anyio
async def test_test_design_gate_pack_disabled(tmp_path, monkeypatch) -> None:
    registry = _wired_registry(tmp_path, monkeypatch, pack_on=False)
    caller = McpCallerContext("ws-a", "default", _TEST_DESIGN_TOOLS)
    names, text = await _deny_payload(
        build_mcp_server(registry=registry, resolver=FixedCallerContextResolver(caller))
    )
    assert names == []
    assert json.loads(text)["code"] == TOOL_UNAVAILABLE_CODE


@pytest.mark.anyio
async def test_test_design_gate_not_allowlisted(tmp_path, monkeypatch) -> None:
    registry = _wired_registry(tmp_path, monkeypatch)
    caller = McpCallerContext("ws-a", "default", frozenset({SEARCH_TOOL}))
    names, text = await _deny_payload(
        build_mcp_server(registry=registry, resolver=FixedCallerContextResolver(caller))
    )
    assert names == [SEARCH_TOOL]
    assert json.loads(text)["code"] == TOOL_UNAVAILABLE_CODE


@pytest.mark.anyio
async def test_test_design_gate_unauthorized_caller(tmp_path, monkeypatch) -> None:
    registry = _wired_registry(tmp_path, monkeypatch)
    names, text = await _deny_payload(
        build_mcp_server(registry=registry, resolver=_UnauthorizedResolver())
    )
    assert names == []
    assert json.loads(text)["code"] == TOOL_UNAVAILABLE_CODE


@pytest.mark.anyio
async def test_test_design_denials_are_byte_identical(tmp_path, monkeypatch) -> None:
    enabled = _wired_registry(tmp_path, monkeypatch)
    disabled = _wired_registry(tmp_path, monkeypatch, pack_on=False)
    allowed = McpCallerContext("ws-a", "default", _TEST_DESIGN_TOOLS)
    not_allowed = McpCallerContext("ws-a", "default", frozenset())

    _, disabled_text = await _deny_payload(
        build_mcp_server(registry=disabled, resolver=FixedCallerContextResolver(allowed))
    )
    _, unlisted_text = await _deny_payload(
        build_mcp_server(
            registry=enabled, resolver=FixedCallerContextResolver(not_allowed)
        )
    )
    _, unauthorized_text = await _deny_payload(
        build_mcp_server(registry=enabled, resolver=_UnauthorizedResolver())
    )

    assert disabled_text == unlisted_text == unauthorized_text


def test_chat_build_tools_remains_drive_only() -> None:
    from packs.software_delivery.registration import build_mcp_tools, build_tools

    assert build_tools() == ()
    assert build_mcp_tools() == ()
