"""Composition MCP registry authorization and core search projection."""

from __future__ import annotations

import json

import pytest

from application.contracts import RetrieveRequest, RetrieveResponse
from composition.mcp_access import McpCallerContext
from composition.mcp_search_knowledge import (
    SearchKnowledgeTool,
    TOOL_NAME,
    project_search_result,
)
from composition.mcp_tool_registry import (
    TOOL_UNAVAILABLE_CODE,
    McpToolContribution,
    McpToolRegistry,
)
from domain.knowledge import (
    DocumentChunk,
    ScoredChunk,
    SourceMetadata,
    SourceReference,
)


class _StubRetrieve:
    def __init__(self, hits: tuple[ScoredChunk, ...] = ()) -> None:
        self._hits = hits
        self.calls: list[RetrieveRequest] = []

    def execute(self, request: RetrieveRequest) -> RetrieveResponse:
        self.calls.append(request)
        return RetrieveResponse(hits=self._hits)


def _hit(source_id: str, content: str, score: float = 0.9) -> ScoredChunk:
    ref = SourceReference(source_id, "doc")
    chunk = DocumentChunk(
        metadata=SourceMetadata(
            reference=ref,
            title="t",
            extra={"secret_path": "/internal/x"},
        ),
        index=0,
        content=content,
    )
    return ScoredChunk(chunk=chunk, score=score)


def test_list_effective_respects_allowlist() -> None:
    registry = McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id=TOOL_NAME,
                pack_id=None,
                factory=lambda: SearchKnowledgeTool(_StubRetrieve()),
            ),
        ),
        enabled_packs=("software-delivery",),
    )
    caller = McpCallerContext("ws", "default", frozenset({TOOL_NAME}))
    names = [item.name for item in registry.list_effective(caller)]
    assert names == [TOOL_NAME]


def test_invoke_non_allowlisted_is_tool_unavailable() -> None:
    registry = McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id=TOOL_NAME,
                pack_id=None,
                factory=lambda: SearchKnowledgeTool(_StubRetrieve()),
            ),
        ),
        enabled_packs=(),
    )
    caller = McpCallerContext("ws", "default", frozenset())
    result = registry.invoke_authorized(caller, TOOL_NAME, {"query": "x"})
    assert result.is_error
    assert result.code == TOOL_UNAVAILABLE_CODE


def test_stale_pack_tool_allowlist_is_unavailable_when_not_contributed() -> None:
    """Retired scaffolding IDs must not revive when only allowlisted."""
    registry = McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id=TOOL_NAME,
                pack_id=None,
                factory=lambda: SearchKnowledgeTool(_StubRetrieve()),
            ),
        ),
        enabled_packs=("software-delivery",),
    )
    caller = McpCallerContext(
        "ws",
        "default",
        frozenset({"software_delivery.risk_score", TOOL_NAME}),
    )
    names = [item.name for item in registry.list_effective(caller)]
    assert names == [TOOL_NAME]
    result = registry.invoke_authorized(
        caller, "software_delivery.risk_score", {}
    )
    assert result.is_error
    assert result.code == TOOL_UNAVAILABLE_CODE


def test_unknown_and_drive_share_identical_unavailable() -> None:
    registry = McpToolRegistry(contributions=(), enabled_packs=())
    caller = McpCallerContext("ws", "default", frozenset({"x"}))
    a = registry.invoke_authorized(caller, "no.such.tool", {})
    b = registry.invoke_authorized(
        caller, "software_delivery.export_test_cases_google_drive", {}
    )
    assert a.is_error and b.is_error
    assert a.text == b.text
    assert a.code == b.code == TOOL_UNAVAILABLE_CODE


def test_search_knowledge_projection_excludes_extra_and_marks_untrusted() -> None:
    hits = (_hit("src-1", "hello evidence"),)
    result = project_search_result(hits)
    payload = result.model_dump(mode="json")
    assert payload["evidence"][0]["untrusted_evidence"] is True
    assert "secret_path" not in json.dumps(payload)
    assert payload["citations"][0]["source"]["source_id"] == "src-1"


def test_search_knowledge_tool_returns_structured_json() -> None:
    tool = SearchKnowledgeTool(_StubRetrieve(hits=(_hit("s", "body"),)))
    raw = tool.run({"query": "how?", "retrieval_limit": 3})
    data = json.loads(raw)
    assert data["evidence"][0]["content"] == "body"
    assert data["citations"][0]["chunk_index"] == 0


def test_build_mcp_tools_returns_empty_until_live_tools() -> None:
    from packs.software_delivery.registration import build_mcp_tools, build_tools

    assert build_mcp_tools() == ()
    assert build_tools() == ()


def test_build_mcp_registry_without_packs_exposes_only_core() -> None:
    from dataclasses import replace

    from composition.mcp_access import McpCallerContext
    from composition.mcp_wiring import build_mcp_tool_registry
    from infrastructure.config import DomainToolSettings, load_settings

    settings = replace(
        load_settings(),
        domain_tools=DomainToolSettings(enabled_packs=()),
    )
    registry = build_mcp_tool_registry(settings, retrieve=_StubRetrieve())
    caller = McpCallerContext("ws", "default", frozenset({TOOL_NAME}))
    assert [item.name for item in registry.list_effective(caller)] == [TOOL_NAME]


def test_build_mcp_registry_with_pack_enabled_keeps_empty_seam() -> None:
    from dataclasses import replace

    from composition.mcp_access import McpCallerContext
    from composition.mcp_wiring import build_mcp_tool_registry
    from infrastructure.config import DomainToolSettings, load_settings

    settings = replace(
        load_settings(),
        domain_tools=DomainToolSettings(enabled_packs=("software-delivery",)),
    )
    registry = build_mcp_tool_registry(settings, retrieve=_StubRetrieve())
    caller = McpCallerContext(
        "ws",
        "default",
        frozenset({TOOL_NAME, "software_delivery.risk_score"}),
    )
    assert [item.name for item in registry.list_effective(caller)] == [TOOL_NAME]


def test_disabled_mcp_registry_does_not_import_software_delivery_pack() -> None:
    """Fresh interpreter: empty DOMAIN_TOOL_PACKS must not load the pack via MCP."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    script = r"""
import sys
from dataclasses import replace

import infrastructure.config as config

config.load_dotenv = lambda *a, **k: False

from application.contracts import RetrieveRequest, RetrieveResponse
from composition.mcp_wiring import build_mcp_tool_registry
from infrastructure.config import DomainToolSettings, load_settings


class _Stub:
    def execute(self, request: RetrieveRequest) -> RetrieveResponse:
        return RetrieveResponse(hits=())


settings = replace(
    load_settings(),
    domain_tools=DomainToolSettings(enabled_packs=()),
)
build_mcp_tool_registry(settings, retrieve=_Stub())
assert not any(
    name == "packs.software_delivery"
    or name.startswith("packs.software_delivery.")
    for name in sys.modules
)
print("ok", flush=True)
"""
    env = {
        **os.environ,
        "PYTHONPATH": str(project_root),
        "DOMAIN_TOOL_PACKS": "",
        "PYTHONUNBUFFERED": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert "ok" in completed.stdout


def test_mcp_wiring_loads_pack_via_allowlist_not_hardcoded_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP contributions come from SUPPORTED_MCP_TOOL_PACKS, not a fixed SD import."""
    from dataclasses import replace
    from types import ModuleType

    import composition.mcp_wiring as mcp_wiring
    from composition.mcp_access import McpCallerContext
    from infrastructure.config import DomainToolSettings, load_settings

    fake = ModuleType("test_fake_mcp_pack")

    def build_mcp_tools(*, chat_model_factory=None):
        _ = chat_model_factory

        class _Tool:
            name = "fake.pack_tool"
            description = "Fake pack MCP tool for wiring tests"
            args_schema = None

            def run(self, arguments: dict) -> str:
                return '{"ok": true}'

        return (("fake.pack_tool", lambda: _Tool()),)

    fake.build_mcp_tools = build_mcp_tools  # type: ignore[attr-defined]
    sys_modules = __import__("sys").modules
    sys_modules["test_fake_mcp_pack"] = fake
    monkeypatch.setitem(
        mcp_wiring.SUPPORTED_MCP_TOOL_PACKS,
        "fake-pack",
        "test_fake_mcp_pack:build_mcp_tools",
    )
    settings = replace(
        load_settings(),
        domain_tools=DomainToolSettings(enabled_packs=("fake-pack",)),
    )
    registry = mcp_wiring.build_mcp_tool_registry(
        settings, retrieve=_StubRetrieve()
    )
    caller = McpCallerContext(
        "ws", "default", frozenset({TOOL_NAME, "fake.pack_tool"})
    )
    names = [item.name for item in registry.list_effective(caller)]
    assert names == [TOOL_NAME, "fake.pack_tool"]
