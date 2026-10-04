"""Composition MCP registry authorization and core search projection."""

from __future__ import annotations

import json

import pytest

from application.contracts import RetrieveRequest, RetrieveResponse
from composition.mcp.access import McpCallerContext
from composition.mcp.search_knowledge import (
    SearchKnowledgeTool,
    TOOL_NAME,
    project_search_result,
)
from composition.mcp.tool_registry import (
    TOOL_UNAVAILABLE_CODE,
    McpToolContribution,
    McpToolRegistry,
    mcp_tool_name,
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
    assert names == [mcp_tool_name(TOOL_NAME)]


def test_advertised_names_have_no_dots() -> None:
    assert mcp_tool_name("software_delivery.test_design_start") == (
        "software_delivery_test_design_start"
    )
    assert mcp_tool_name(TOOL_NAME) == "core_search_knowledge"


def test_invoke_accepts_advertised_name_and_dotted_id() -> None:
    retrieve = _StubRetrieve()
    registry = McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id=TOOL_NAME,
                pack_id=None,
                factory=lambda: SearchKnowledgeTool(retrieve),
            ),
        ),
        enabled_packs=(),
    )
    caller = McpCallerContext("ws", "default", frozenset({TOOL_NAME}))

    for name in (mcp_tool_name(TOOL_NAME), TOOL_NAME):
        result = registry.invoke_authorized(caller, name, {"query": "x"})
        assert result.is_error is False

    assert len(retrieve.calls) == 2


def test_advertised_name_still_requires_allowlist() -> None:
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
    result = registry.invoke_authorized(caller, mcp_tool_name(TOOL_NAME), {"query": "x"})
    assert result.code == TOOL_UNAVAILABLE_CODE


def test_tool_ids_colliding_after_name_mapping_are_rejected() -> None:
    def factory() -> SearchKnowledgeTool:
        return SearchKnowledgeTool(_StubRetrieve())

    with pytest.raises(ValueError, match="duplicate MCP tool name"):
        McpToolRegistry(
            contributions=(
                McpToolContribution(tool_id="a.b", pack_id=None, factory=factory),
                McpToolContribution(tool_id="a_b", pack_id=None, factory=factory),
            ),
            enabled_packs=(),
        )


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
    assert names == [mcp_tool_name(TOOL_NAME)]
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


class _RaisingTool:
    name = "fake.raising"
    description = "Raises the configured error"
    args_schema = None

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def run(self, arguments: dict) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return '{"ok":true}'


def _registry_for(
    tool: _RaisingTool, *, enabled_packs: tuple[str, ...] = ("software-delivery",)
) -> McpToolRegistry:
    return McpToolRegistry(
        contributions=(
            McpToolContribution(
                tool_id=tool.name, pack_id="software-delivery", factory=lambda: tool
            ),
        ),
        enabled_packs=enabled_packs,
    )


_SECRET = "ws-secret token=gho_x fp=abc /internal/path"


@pytest.mark.parametrize(
    ("error_cls", "code"),
    [
        ("ToolTargetNotFoundError", "not_found"),
        ("ToolVersionConflictError", "version_conflict"),
        ("ToolEvidenceChangedError", "evidence_changed"),
        ("ToolInsufficientEvidenceError", "insufficient_evidence"),
    ],
)
def test_neutral_tool_errors_translate_to_allowlisted_safe_codes(
    error_cls: str, code: str
) -> None:
    import domain.errors as domain_errors

    tool = _RaisingTool(getattr(domain_errors, error_cls)(_SECRET))
    caller = McpCallerContext("ws", "default", frozenset({tool.name}))

    result = _registry_for(tool).invoke_authorized(caller, tool.name, {})

    assert result.is_error
    assert result.code == code
    assert result.structured is not None
    assert result.structured["code"] == code
    assert set(result.structured) == {"code", "message"}
    assert _SECRET not in result.text
    assert json.loads(result.text) == result.structured


def test_source_not_connected_carries_the_legacy_github_alias() -> None:
    from domain.errors import ToolSourceNotConnectedError

    tool = _RaisingTool(ToolSourceNotConnectedError(_SECRET))
    caller = McpCallerContext("ws", "default", frozenset({tool.name}))

    result = _registry_for(tool).invoke_authorized(caller, tool.name, {})

    assert result.is_error
    assert result.code == "source_not_connected"
    assert result.structured == {
        "code": "source_not_connected",
        "legacy_code": "github_not_connected",
        "message": "Source is not connected",
    }
    assert _SECRET not in result.text
    assert json.loads(result.text) == result.structured


_FALLBACK = "fake.fallback"
_FALLBACK_PACK = "fallback-pack"
_HINT = "Try the fallback tool."


class _HintedTool(_RaisingTool):
    failure_hints = {"source_not_connected": (_FALLBACK, _HINT)}


def _hinted_registry(
    tool: _RaisingTool,
    *,
    fallback_contributed: bool = True,
    enabled_packs: tuple[str, ...] = ("software-delivery", _FALLBACK_PACK),
) -> McpToolRegistry:
    contributions = [
        McpToolContribution(
            tool_id=tool.name, pack_id="software-delivery", factory=lambda: tool
        )
    ]
    if fallback_contributed:
        contributions.append(
            McpToolContribution(
                tool_id=_FALLBACK,
                pack_id=_FALLBACK_PACK,
                factory=lambda: _RaisingTool(),
            )
        )
    return McpToolRegistry(contributions=contributions, enabled_packs=enabled_packs)


def _source_not_connected() -> Exception:
    from domain.errors import ToolSourceNotConnectedError

    return ToolSourceNotConnectedError(_SECRET)


def test_failure_hint_is_added_when_the_fallback_tool_is_effective() -> None:
    tool = _HintedTool(_source_not_connected())
    caller = McpCallerContext("ws", "default", frozenset({tool.name, _FALLBACK}))

    result = _hinted_registry(tool).invoke_authorized(caller, tool.name, {})

    assert result.code == "source_not_connected"
    assert result.structured == {
        "code": "source_not_connected",
        "message": "Source is not connected",
        "legacy_code": "github_not_connected",
        "hint": _HINT,
    }
    assert json.loads(result.text) == result.structured
    assert _SECRET not in result.text


def _unhinted_source_not_connected(caller: McpCallerContext):  # noqa: ANN202
    tool = _RaisingTool(_source_not_connected())
    tool.name = _HintedTool.name
    return _hinted_registry(tool).invoke_authorized(caller, tool.name, {})


@pytest.mark.parametrize(
    ("allowlist", "registry_kwargs"),
    [
        pytest.param(frozenset({"fake.raising"}), {}, id="fallback-not-allowlisted"),
        pytest.param(
            frozenset({"fake.raising", _FALLBACK}),
            {"enabled_packs": ("software-delivery",)},
            id="fallback-pack-disabled",
        ),
        pytest.param(
            frozenset({"fake.raising", _FALLBACK}),
            {"fallback_contributed": False},
            id="fallback-not-contributed",
        ),
    ],
)
def test_failure_hint_is_withheld_unless_the_fallback_tool_is_effective(
    allowlist: frozenset[str], registry_kwargs: dict
) -> None:
    tool = _HintedTool(_source_not_connected())
    caller = McpCallerContext("ws", "default", allowlist)

    result = _hinted_registry(tool, **registry_kwargs).invoke_authorized(
        caller, tool.name, {}
    )

    unhinted = _unhinted_source_not_connected(caller)
    assert result.structured == {
        "code": "source_not_connected",
        "message": "Source is not connected",
        "legacy_code": "github_not_connected",
    }
    assert result.text == unhinted.text
    assert result.structured == unhinted.structured


def test_failure_hint_is_only_added_for_the_hinted_code() -> None:
    from domain.errors import ToolTargetNotFoundError

    tool = _HintedTool(ToolTargetNotFoundError(_SECRET))
    caller = McpCallerContext("ws", "default", frozenset({tool.name, _FALLBACK}))

    result = _hinted_registry(tool).invoke_authorized(caller, tool.name, {})

    assert result.structured == {"code": "not_found", "message": "Resource not found"}


def test_safe_code_messages_are_fixed_per_code() -> None:
    from domain.errors import ToolTargetNotFoundError

    caller = McpCallerContext("ws", "default", frozenset({"fake.raising"}))
    a = _registry_for(_RaisingTool(ToolTargetNotFoundError("a"))).invoke_authorized(
        caller, "fake.raising", {}
    )
    b = _registry_for(_RaisingTool(ToolTargetNotFoundError("b"))).invoke_authorized(
        caller, "fake.raising", {}
    )
    assert a.text == b.text


def test_argument_validation_stays_validation_error() -> None:
    from domain.errors import ToolArgumentValidationError

    tool = _RaisingTool(ToolArgumentValidationError(_SECRET))
    caller = McpCallerContext("ws", "default", frozenset({tool.name}))

    result = _registry_for(tool).invoke_authorized(caller, tool.name, {})

    assert result.code == "validation_error"
    assert _SECRET not in result.text


class _SchemaTool(_RaisingTool):
    def __init__(self, args_schema: type) -> None:
        super().__init__()
        self.args_schema = args_schema


def _schema_rejecting_with(error_type: str) -> type:
    from pydantic import BaseModel, model_validator
    from pydantic_core import PydanticCustomError

    class _Args(BaseModel):
        @model_validator(mode="after")
        def _reject(self):  # noqa: ANN202
            raise PydanticCustomError(error_type, "Fixed safe message.")

    return _Args


def test_safe_schema_validation_message_is_returned() -> None:
    from composition.mcp.tool_registry import SAFE_VALIDATION_ERROR_TYPE

    tool = _SchemaTool(_schema_rejecting_with(SAFE_VALIDATION_ERROR_TYPE))
    caller = McpCallerContext("ws", "default", frozenset({tool.name}))

    result = _registry_for(tool).invoke_authorized(caller, tool.name, {})

    assert result.code == "validation_error"
    assert json.loads(result.text)["message"] == "Fixed safe message."
    assert tool.calls == 0


def test_other_schema_validation_messages_stay_generic() -> None:
    tool = _SchemaTool(_schema_rejecting_with("value_error"))
    caller = McpCallerContext("ws", "default", frozenset({tool.name}))

    result = _registry_for(tool).invoke_authorized(caller, tool.name, {})

    assert json.loads(result.text)["message"] == "Invalid tool arguments"


@pytest.mark.parametrize(
    "error",
    [
        __import__("domain.errors").errors.ToolFailureError(_SECRET),
        RuntimeError(_SECRET),
        KeyError(_SECRET),
    ],
)
def test_unexpected_or_generic_failures_become_internal_error(error: Exception) -> None:
    tool = _RaisingTool(error)
    caller = McpCallerContext("ws", "default", frozenset({tool.name}))

    result = _registry_for(tool).invoke_authorized(caller, tool.name, {})

    assert result.code == "internal_error"
    assert _SECRET not in result.text


def test_unavailable_capability_is_identical_to_deny() -> None:
    from domain.errors import ToolUnavailableError

    tool = _RaisingTool(ToolUnavailableError(_SECRET))
    allowed = McpCallerContext("ws", "default", frozenset({tool.name}))
    denied = McpCallerContext("ws", "default", frozenset())
    registry = _registry_for(tool)

    raised = registry.invoke_authorized(allowed, tool.name, {})
    deny = registry.invoke_authorized(denied, tool.name, {})

    assert raised.code == TOOL_UNAVAILABLE_CODE
    assert raised.text == deny.text
    assert raised.structured == deny.structured


def test_gate_enabled_allowlisted_authorized_is_listed_and_invocable() -> None:
    tool = _RaisingTool()
    caller = McpCallerContext("ws", "default", frozenset({tool.name}))
    registry = _registry_for(tool)

    assert [d.name for d in registry.list_effective(caller)] == [
        mcp_tool_name(tool.name)
    ]
    result = registry.invoke_authorized(caller, tool.name, {})
    assert result.is_error is False
    assert tool.calls == 1


def test_gate_pack_not_enabled_is_unlisted_and_unavailable() -> None:
    tool = _RaisingTool()
    caller = McpCallerContext("ws", "default", frozenset({tool.name}))
    registry = _registry_for(tool, enabled_packs=())

    assert registry.list_effective(caller) == ()
    result = registry.invoke_authorized(caller, tool.name, {})
    assert result.code == TOOL_UNAVAILABLE_CODE
    assert tool.calls == 0


def test_gate_not_allowlisted_is_unlisted_and_unavailable() -> None:
    tool = _RaisingTool()
    caller = McpCallerContext("ws", "default", frozenset({"other.tool"}))
    registry = _registry_for(tool)

    assert registry.list_effective(caller) == ()
    result = registry.invoke_authorized(caller, tool.name, {})
    assert result.code == TOOL_UNAVAILABLE_CODE
    assert tool.calls == 0


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

    from composition.mcp.access import McpCallerContext
    from composition.mcp.wiring import build_mcp_tool_registry
    from infrastructure.config import DomainToolSettings, load_settings

    settings = replace(
        load_settings(),
        domain_tools=DomainToolSettings(enabled_packs=()),
    )
    registry = build_mcp_tool_registry(settings, retrieve=_StubRetrieve())
    caller = McpCallerContext("ws", "default", frozenset({TOOL_NAME}))
    assert [item.name for item in registry.list_effective(caller)] == [
        mcp_tool_name(TOOL_NAME)
    ]


def test_build_mcp_registry_with_pack_enabled_keeps_empty_seam() -> None:
    from dataclasses import replace

    from composition.mcp.access import McpCallerContext
    from composition.mcp.wiring import build_mcp_tool_registry
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
    assert [item.name for item in registry.list_effective(caller)] == [
        mcp_tool_name(TOOL_NAME)
    ]


_TEST_DESIGN_TOOLS = (
    "software_delivery.test_design_confirm",
    "software_delivery.test_design_export_feature",
    "software_delivery.test_design_generate",
    "software_delivery.test_design_get",
    "software_delivery.test_design_start",
    "software_delivery.test_design_start_from_text",
)


def _test_design_registry(
    tmp_path, monkeypatch: pytest.MonkeyPatch, *, workspace_id: str, pack_on: bool = True
):
    import composition.container as container
    from composition.mcp.wiring import build_mcp_tool_registry
    from test.composition.test_design.test_design_fakes import (
        build_fake_facade,
        settings_with_pack,
    )

    settings = settings_with_pack(pack_on=pack_on, workspace_id=workspace_id)
    monkeypatch.setattr(
        container,
        "build_test_design_facade",
        lambda active: build_fake_facade(
            tmp_path, workspace_id=active.document_catalog.workspace_id
        ),
    )
    return build_mcp_tool_registry(settings, retrieve=_StubRetrieve())


def test_wired_test_design_tools_are_listed_when_enabled_and_allowlisted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _test_design_registry(tmp_path, monkeypatch, workspace_id="ws-a")
    caller = McpCallerContext("ws-a", "default", frozenset(_TEST_DESIGN_TOOLS))

    names = [item.name for item in registry.list_effective(caller)]

    assert names == [mcp_tool_name(tool_id) for tool_id in _TEST_DESIGN_TOOLS]


def test_wired_test_design_tools_absent_when_pack_disabled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _test_design_registry(
        tmp_path, monkeypatch, workspace_id="ws-a", pack_on=False
    )
    caller = McpCallerContext("ws-a", "default", frozenset(_TEST_DESIGN_TOOLS))

    assert registry.list_effective(caller) == ()
    result = registry.invoke_authorized(
        caller, "software_delivery.test_design_get", {"draft_id": "d"}
    )
    assert result.code == TOOL_UNAVAILABLE_CODE


def test_cross_workspace_draft_is_identical_to_unknown_draft(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test.composition.test_design.test_design_fakes import ISSUE_LOCATOR

    registry_a = _test_design_registry(tmp_path, monkeypatch, workspace_id="ws-a")
    caller_a = McpCallerContext("ws-a", "default", frozenset(_TEST_DESIGN_TOOLS))
    started = registry_a.invoke_authorized(
        caller_a, "software_delivery.test_design_start", {"issue_locator": ISSUE_LOCATOR}
    )
    assert started.is_error is False
    draft_id = json.loads(started.text)["draft_id"]
    own = registry_a.invoke_authorized(
        caller_a, "software_delivery.test_design_get", {"draft_id": draft_id}
    )
    assert own.is_error is False

    registry_b = _test_design_registry(tmp_path, monkeypatch, workspace_id="ws-b")
    caller_b = McpCallerContext("ws-b", "default", frozenset(_TEST_DESIGN_TOOLS))
    cross = registry_b.invoke_authorized(
        caller_b, "software_delivery.test_design_get", {"draft_id": draft_id}
    )
    unknown = registry_b.invoke_authorized(
        caller_b, "software_delivery.test_design_get", {"draft_id": "no-such-draft"}
    )

    assert cross.code == "not_found"
    assert cross.text == unknown.text
    assert draft_id not in cross.text


def test_build_mcp_tools_contributes_test_design_only_with_binding() -> None:
    from composition.mcp.test_design import McpTestDesignBinding
    from packs.software_delivery.registration import build_mcp_tools

    contributed = build_mcp_tools(
        test_design_binding=McpTestDesignBinding(lambda: object())  # type: ignore[arg-type,return-value]
    )

    assert sorted(tool_id for tool_id, _ in contributed) == list(_TEST_DESIGN_TOOLS)
    assert sorted(factory().name for _, factory in contributed) == list(
        _TEST_DESIGN_TOOLS
    )


def test_disabled_mcp_registry_does_not_import_software_delivery_pack() -> None:
    """Fresh interpreter: empty DOMAIN_TOOL_PACKS must not load the pack via MCP."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[3]
    script = r"""
import sys
from dataclasses import replace

import infrastructure.config as config

config.load_dotenv = lambda *a, **k: False

from application.contracts import RetrieveRequest, RetrieveResponse
from composition.mcp.wiring import build_mcp_tool_registry
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


def test_disabled_http_deps_do_not_import_any_pack() -> None:
    """Fresh interpreter: the HTTP composition path must not load packs eagerly."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[3]
    script = r"""
import sys

import infrastructure.config as config

config.load_dotenv = lambda *a, **k: False

import presentation.http.deps  # noqa: F401
import presentation.http.routes.chat  # noqa: F401
import presentation.http.routes.test_design  # noqa: F401

loaded = sorted(name for name in sys.modules if name.split(".")[0] == "packs")
assert not loaded, loaded
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

    import composition.mcp.wiring as mcp_wiring
    from composition.mcp.access import McpCallerContext
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
    monkeypatch.setitem(__import__("sys").modules, "test_fake_mcp_pack", fake)
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
    assert names == [mcp_tool_name(TOOL_NAME), "fake_pack_tool"]
