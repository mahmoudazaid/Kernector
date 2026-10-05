"""Protocol E2E: core.search_knowledge and MCP deny paths (no scaffolding tools)."""

from __future__ import annotations

import json

import pytest
from mcp import Client

from application.contracts import RetrieveRequest, RetrieveResponse
from composition.mcp.access import FixedCallerContextResolver, McpCallerContext
from composition.mcp.search_knowledge import TOOL_NAME as SEARCH_TOOL
from composition.mcp.search_knowledge import SearchKnowledgeTool
from composition.mcp.tool_registry import (
    TOOL_UNAVAILABLE_CODE,
    McpToolContribution,
    McpToolRegistry,
    mcp_tool_name,
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
        assert names == ["core_search_knowledge"]
        tool = listed.tools[0]
        assert "evidence" in (tool.description or "").lower()
        assert tool.input_schema is not None
        result = await client.call_tool(
            tool.name, {"query": "restart service", "retrieval_limit": 3}
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
        assert [t.name for t in listed.tools] == [mcp_tool_name(SEARCH_TOOL)]
        results = []
        for name in (
            "nope.tool",
            "software_delivery.risk_score",
            "software_delivery_risk_score",
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
        "software_delivery.test_design_start_from_text",
        "software_delivery.test_design_get",
        "software_delivery.test_design_confirm",
        "software_delivery.test_design_generate",
        "software_delivery.test_design_export_feature",
    }
)


def _wired_registry(
    tmp_path, monkeypatch: pytest.MonkeyPatch, *, pack_on: bool = True, **facade_kwargs
):
    import composition.container as container
    from composition.mcp.wiring import build_mcp_tool_registry
    from test.composition.test_design.test_design_fakes import build_fake_facade, settings_with_pack

    settings = settings_with_pack(pack_on=pack_on, workspace_id="ws-a")
    monkeypatch.setattr(
        container,
        "build_test_design_facade",
        lambda _settings: build_fake_facade(
            tmp_path, workspace_id="ws-a", **facade_kwargs
        ),
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
    from test.composition.test_design.test_design_fakes import ISSUE_LOCATOR

    registry = _wired_registry(tmp_path, monkeypatch)
    caller = McpCallerContext("ws-a", "default", _TEST_DESIGN_TOOLS)
    server = build_mcp_server(
        registry=registry, resolver=FixedCallerContextResolver(caller)
    )
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        assert {tool.name for tool in listed.tools} == {
            mcp_tool_name(tool_id) for tool_id in _TEST_DESIGN_TOOLS
        }
        for tool in listed.tools:
            assert "workspace_id" not in json.dumps(tool.input_schema)
            assert "workspace_id" not in json.dumps(tool.output_schema)

        started = await _call(
            client,
            "software_delivery_test_design_start",
            {"issue_locator": ISSUE_LOCATOR},
        )
        assert started["status"] == "coverage_review"
        assert started["version"] == 1
        assert started["ticket_identifier"] == ISSUE_LOCATOR
        assert all(c["untrusted_model_output"] for c in started["candidates"])
        draft_id = started["draft_id"]

        fetched = await _call(
            client, "software_delivery_test_design_get", {"draft_id": draft_id}
        )
        assert fetched["version"] == 1
        assert fetched["candidates"] == started["candidates"]

        confirmed = await _call(
            client,
            "software_delivery_test_design_confirm",
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
            "software_delivery_test_design_generate",
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

        exported = await _call(
            client,
            "software_delivery_test_design_export_feature",
            {"draft_id": draft_id},
        )
        assert exported["filename"] == "login.feature"
        assert exported["scenario_count"] == 1
        assert exported["content"].startswith(
            "Feature: Login\n\n  Background:\n    Given the login page is open\n"
        )
        assert "Given a locked account" in exported["content"]

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


_CLIENT_SENTINELS = ("SENTINEL-355-BODY", "SENTINEL-355-AC")
_CLIENT_CONTENT = {
    "ticket_identifier": "KERN-355",
    "title": "Login",
    "body": "Users sign in with email and password. SENTINEL-355-BODY",
    "acceptance_criteria": "- Lockout after 5 failures SENTINEL-355-AC",
    "source_url": "https://tracker.example/KERN-355",
}


def _assert_client_supplied_without_evidence(result: dict) -> None:
    assert result["evidence_origin"] == "client_supplied"
    encoded = json.dumps(result)
    assert "client_evidence_text" not in encoded
    for sentinel in _CLIENT_SENTINELS:
        assert sentinel not in encoded


@pytest.mark.anyio
async def test_test_design_from_client_content_e2e_via_protocol_client(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _wired_registry(tmp_path, monkeypatch)
    caller = McpCallerContext("ws-a", "default", _TEST_DESIGN_TOOLS)
    server = build_mcp_server(
        registry=registry, resolver=FixedCallerContextResolver(caller)
    )
    async with Client(server, raise_exceptions=True) as client:
        listed = {tool.name: tool for tool in (await client.list_tools()).tools}
        tool = listed["software_delivery_test_design_start_from_text"]
        assert "workspace_id" not in json.dumps(tool.input_schema)
        assert "client_evidence_text" not in json.dumps(tool.output_schema)

        started = await _call(
            client, "software_delivery_test_design_start_from_text", _CLIENT_CONTENT
        )
        assert started["status"] == "coverage_review"
        assert started["version"] == 1
        assert started["ticket_identifier"] == "KERN-355"
        _assert_client_supplied_without_evidence(started)
        draft_id = started["draft_id"]

        fetched = await _call(
            client, "software_delivery_test_design_get", {"draft_id": draft_id}
        )
        assert fetched["candidates"] == started["candidates"]
        _assert_client_supplied_without_evidence(fetched)

        confirmed = await _call(
            client,
            "software_delivery_test_design_confirm",
            {
                "draft_id": draft_id,
                "expected_version": 1,
                "candidate_ids": ["cand-1", "cand-2"],
            },
        )
        assert confirmed["status"] == "ready"
        _assert_client_supplied_without_evidence(confirmed)

        generated = await _call(
            client,
            "software_delivery_test_design_generate",
            {
                "draft_id": draft_id,
                "expected_version": confirmed["version"],
                "type_overrides": [
                    {"candidate_id": "cand-1", "test_type": "manual"},
                    {"candidate_id": "cand-2", "test_type": "cucumber"},
                ],
            },
        )
        assert generated["status"] == "case_editing"
        assert {case["candidate_id"] for case in generated["generated_cases"]} == {
            "cand-1",
            "cand-2",
        }
        _assert_client_supplied_without_evidence(generated)

        final = await _call(
            client, "software_delivery_test_design_get", {"draft_id": draft_id}
        )
        assert final["version"] == generated["version"]
        assert final["generated_cases"] == generated["generated_cases"]
        _assert_client_supplied_without_evidence(final)

        exported = await _call(
            client,
            "software_delivery_test_design_export_feature",
            {"draft_id": draft_id},
        )
        assert exported["scenario_count"] == 1
        _assert_client_supplied_without_evidence(exported)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments",
    [
        {**_CLIENT_CONTENT, "body": "x" * 20_001},
        {**_CLIENT_CONTENT, "workspace_id": "ws-b"},
        {**_CLIENT_CONTENT, "ticket_identifier": "KERN 355"},
    ],
)
async def test_invalid_client_content_is_a_validation_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch, arguments: dict
) -> None:
    import composition.mcp.test_design as mcp_test_design

    registry = _wired_registry(tmp_path, monkeypatch)
    calls: list[object] = []
    original = mcp_test_design.McpTestDesignOperations.start_from_content

    def _spy(self, **kwargs):  # noqa: ANN001, ANN003, ANN202
        calls.append(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(
        mcp_test_design.McpTestDesignOperations, "start_from_content", _spy
    )
    caller = McpCallerContext("ws-a", "default", _TEST_DESIGN_TOOLS)
    server = build_mcp_server(
        registry=registry, resolver=FixedCallerContextResolver(caller)
    )
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "software_delivery_test_design_start_from_text", arguments
        )

    assert result.is_error is True
    assert json.loads(result.content[0].text)["code"] == "validation_error"
    assert calls == []


def _content_with_combined_chars(total: int) -> dict:
    criteria = "y" * 5_000
    used = (
        len(_CLIENT_CONTENT["title"])
        + len(_CLIENT_CONTENT["source_url"])
        + len(criteria)
    )
    return {
        **_CLIENT_CONTENT,
        "ticket_identifier": "K" * 160,
        "body": "x" * (total - used),
        "acceptance_criteria": criteria,
    }


@pytest.mark.anyio
async def test_client_content_at_the_published_limit_is_accepted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _wired_registry(tmp_path, monkeypatch)
    caller = McpCallerContext("ws-a", "default", _TEST_DESIGN_TOOLS)
    server = build_mcp_server(
        registry=registry, resolver=FixedCallerContextResolver(caller)
    )
    async with Client(server, raise_exceptions=True) as client:
        started = await _call(
            client,
            "software_delivery_test_design_start_from_text",
            _content_with_combined_chars(9_775),
        )

    assert started["status"] == "coverage_review"


@pytest.mark.anyio
async def test_client_content_over_the_combined_limit_says_what_to_shorten(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _wired_registry(tmp_path, monkeypatch)
    caller = McpCallerContext("ws-a", "default", _TEST_DESIGN_TOOLS)
    server = build_mcp_server(
        registry=registry, resolver=FixedCallerContextResolver(caller)
    )
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "software_delivery_test_design_start_from_text",
            _content_with_combined_chars(9_776),
        )

    assert result.is_error is True
    assert json.loads(result.content[0].text) == {
        "code": "validation_error",
        "message": (
            "Issue content is too long. Title, body, acceptance_criteria and "
            "source_url together must fit in 9,775 characters; shorten the "
            "body first and keep the acceptance criteria."
        ),
    }


@pytest.mark.anyio
async def test_start_from_content_requires_its_own_allowlist_entry(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _wired_registry(tmp_path, monkeypatch)
    live_only = McpCallerContext(
        "ws-a",
        "default",
        _TEST_DESIGN_TOOLS - {"software_delivery.test_design_start_from_text"},
    )
    server = build_mcp_server(
        registry=registry, resolver=FixedCallerContextResolver(live_only)
    )
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        denied = await client.call_tool(
            "software_delivery_test_design_start_from_text", _CLIENT_CONTENT
        )
        unknown = await client.call_tool("nope.tool", {})

    assert "software_delivery_test_design_start_from_text" not in {
        tool.name for tool in listed.tools
    }
    assert denied.is_error is True
    assert denied.content[0].text == unknown.content[0].text


_KERNECTOR_JIRA = "https://jira.example.com/jira"
_START_FROM_TEXT = "software_delivery.test_design_start_from_text"
_START_FROM_TEXT_HINT = (
    "If you can read the issue with your own tracker tools, call the "
    "test_design_start_from_text tool with its content."
)


class _KernectorJiraClient:
    """Kernector's own Jira connection: serves ENG-7 as the Login issue."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.error = error

    def get_issue(self, key: str, fields: object) -> dict[str, object]:
        self.calls.append(key)
        if self.error is not None:
            raise self.error
        return {
            "id": "10001",
            "key": key,
            "fields": {
                "summary": "Login",
                "description": "Acceptance criteria: login, lockout, password length.",
                "updated": "2026-09-14T12:00:00.000+0000",
            },
        }


def _github_and_kernector_jira(
    tmp_path, client: _KernectorJiraClient, *, token: str | None = "dc-token"
):
    from composition.test_design.jira_data_center_source import (
        JiraDataCenterTestDesignSource,
    )
    from composition.test_design.sources import TestDesignSourceRegistry
    from infrastructure.config import JiraDataCenterSettings
    from infrastructure.connectors.jira.data_center_state import (
        JiraDataCenterStateStore,
    )
    from test.composition.test_design.test_design_fakes import github_sources

    settings = JiraDataCenterSettings(
        base_url=_KERNECTOR_JIRA,
        token=token,
        state_path=tmp_path / "jira-dc-connection.json",
    )
    jira = JiraDataCenterTestDesignSource(
        settings_provider=lambda: settings,
        state_store=JiraDataCenterStateStore(settings.state_path),
        client_factory=lambda _base_url, _token: client,
    )
    return TestDesignSourceRegistry((github_sources().resolve("github"), jira))


def _jira_server(tmp_path, monkeypatch, client, *, allowlist=_TEST_DESIGN_TOOLS, **kw):
    registry = _wired_registry(
        tmp_path,
        monkeypatch,
        sources=_github_and_kernector_jira(tmp_path, client, **kw),
    )
    caller = McpCallerContext("ws-a", "default", allowlist)
    return build_mcp_server(registry=registry, resolver=FixedCallerContextResolver(caller))


async def _start_error(server, issue_locator: str) -> dict:
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "software_delivery_test_design_start", {"issue_locator": issue_locator}
        )
    assert result.is_error is True
    payload = json.loads(result.content[0].text)
    assert "http" not in result.content[0].text
    assert "example.com" not in result.content[0].text
    return payload


@pytest.mark.anyio
@pytest.mark.parametrize("locator", ["ENG-7", f"{_KERNECTOR_JIRA}/browse/ENG-7"])
async def test_scenarios_1_and_3_live_start_reads_kernector_jira(
    tmp_path, monkeypatch: pytest.MonkeyPatch, locator: str
) -> None:
    jira = _KernectorJiraClient()
    server = _jira_server(tmp_path, monkeypatch, jira)

    async with Client(server, raise_exceptions=True) as client:
        started = await _call(
            client, "software_delivery_test_design_start", {"issue_locator": locator}
        )

    assert jira.calls == ["ENG-7"]
    assert started["ticket_identifier"] == "ENG-7"
    assert started["evidence_origin"] == "live"


@pytest.mark.anyio
async def test_scenario_2_not_connected_hints_at_start_from_text(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = _jira_server(tmp_path, monkeypatch, _KernectorJiraClient(), token=None)

    payload = await _start_error(server, "ENG-7")

    assert payload == {
        "code": "source_not_connected",
        "message": "Source is not connected",
        "legacy_code": "github_not_connected",
        "hint": _START_FROM_TEXT_HINT,
    }


@pytest.mark.anyio
async def test_scenario_2_missing_issue_hints_at_start_from_text(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from domain.errors import ConnectorNotFoundError

    jira = _KernectorJiraClient(error=ConnectorNotFoundError("Jira 404 body"))
    server = _jira_server(tmp_path, monkeypatch, jira)

    payload = await _start_error(server, f"{_KERNECTOR_JIRA}/browse/ENG-7")

    assert payload == {
        "code": "not_found",
        "message": "Resource not found",
        "hint": _START_FROM_TEXT_HINT,
    }


@pytest.mark.anyio
async def test_scenario_2_no_hint_when_start_from_text_is_not_allowlisted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = _jira_server(
        tmp_path,
        monkeypatch,
        _KernectorJiraClient(),
        allowlist=_TEST_DESIGN_TOOLS - {_START_FROM_TEXT},
        token=None,
    )

    payload = await _start_error(server, "ENG-7")

    assert payload == {
        "code": "source_not_connected",
        "message": "Source is not connected",
        "legacy_code": "github_not_connected",
    }


_UNSUPPORTED_SOURCE_WITH_HINT = {
    "code": "unsupported_source",
    "message": "No connected source accepts this locator",
    "hint": _START_FROM_TEXT_HINT,
}


@pytest.mark.anyio
async def test_scenario_2_foreign_instance_url_fails_loudly_with_hint(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jira = _KernectorJiraClient()
    server = _jira_server(tmp_path, monkeypatch, jira)

    payload = await _start_error(server, "https://other-jira.example.com/browse/ENG-7")

    assert payload == _UNSUPPORTED_SOURCE_WITH_HINT
    assert jira.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "locator", ["OIE-721", "https://jira.example.com/browse/OIE-721"]
)
async def test_scenario_2_tracker_kernector_has_no_source_for_hints(
    tmp_path, monkeypatch: pytest.MonkeyPatch, locator: str
) -> None:
    registry = _wired_registry(tmp_path, monkeypatch)
    caller = McpCallerContext("ws-a", "default", _TEST_DESIGN_TOOLS)
    server = build_mcp_server(
        registry=registry, resolver=FixedCallerContextResolver(caller)
    )

    payload = await _start_error(server, locator)

    assert payload == _UNSUPPORTED_SOURCE_WITH_HINT


_WRONG_TRACKER_SENTINELS = ("SENTINEL-361-WRONG-BODY", "SENTINEL-361-WRONG-AC")
_WRONG_TRACKER_CONTENT = {
    "ticket_identifier": "ENG-7",
    "title": "Refund payments",
    "body": "Refunds go back to the original card. SENTINEL-361-WRONG-BODY",
    "acceptance_criteria": "- Partial refunds allowed SENTINEL-361-WRONG-AC",
    "source_url": "https://other-jira.example.com/browse/ENG-7",
}


@pytest.mark.anyio
async def test_scenario_4_wrong_client_tracker_content_is_accepted_unverified(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from composition.mcp.test_design import TestDesignDraftResult

    jira = _KernectorJiraClient()
    server = _jira_server(tmp_path, monkeypatch, jira)

    async with Client(server, raise_exceptions=True) as client:
        started = await _call(
            client, "software_delivery_test_design_start_from_text", _WRONG_TRACKER_CONTENT
        )
        confirmed = await _call(
            client,
            "software_delivery_test_design_confirm",
            {
                "draft_id": started["draft_id"],
                "expected_version": started["version"],
                "candidate_ids": ["cand-1"],
            },
        )
        assert jira.calls == []

        live = await _call(
            client, "software_delivery_test_design_start", {"issue_locator": "ENG-7"}
        )

    for result in (started, confirmed):
        assert result["evidence_origin"] == "client_supplied"
        assert result["ticket_identifier"] == "ENG-7"
        assert set(result) == set(TestDesignDraftResult.model_fields)
        for sentinel in _WRONG_TRACKER_SENTINELS:
            assert sentinel not in json.dumps(result)
    assert jira.calls == ["ENG-7"]
    assert live["evidence_origin"] == "live"


class _UnauthorizedResolver:
    def resolve(self, request: object | None) -> McpCallerContext:
        from composition.mcp.access import MissingCallerContextError

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
    assert names == [mcp_tool_name(SEARCH_TOOL)]
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
