"""Composition wiring for software_delivery.create_xray_tests (#199)."""

from __future__ import annotations

import json

import pytest

from application.contracts import InvokeToolRequest
from application.errors import ConfigurationError
from application.invoke_tool import InvokeTool
from composition.tools.registry import build_tool_registry
from domain.test_management.xray import (
    XrayImportResult,
    XrayTestCreateSchema,
    XrayTestSpec,
)
from infrastructure.config import load_settings
from packs.software_delivery.tools.create_xray_tests import TOOL_NAME


class _Importer:
    def __init__(self) -> None:
        self.specs: list[XrayTestSpec] = []

    def schema(self) -> XrayTestCreateSchema:
        return XrayTestCreateSchema("QA", True, True, True)

    def import_tests(self, specs) -> XrayImportResult:
        self.specs.extend(specs)
        return XrayImportResult(created_keys=("QA-1",), failed_count=0)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in (
        "XRAY_DEPLOYMENT",
        "XRAY_PROJECT_KEY",
        "XRAY_CLIENT_ID",
        "XRAY_CLIENT_SECRET",
        "JIRA_OAUTH_CLIENT_ID",
        "JIRA_OAUTH_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    return monkeypatch


def _cloud(env: pytest.MonkeyPatch) -> None:
    env.setenv("XRAY_DEPLOYMENT", "cloud")
    env.setenv("XRAY_PROJECT_KEY", "QA")
    env.setenv("XRAY_CLIENT_ID", "client-id")
    env.setenv("XRAY_CLIENT_SECRET", "client-secret")


def test_registry_registers_xray_tool_with_atomic_collaborators(env) -> None:
    registry = build_tool_registry(
        load_settings(), xray_importer=_Importer(), xray_load_draft=lambda _id: None
    )

    assert registry.names() == (TOOL_NAME,)


def test_partial_xray_collaborators_are_configuration_error(env) -> None:
    settings = load_settings()

    with pytest.raises(ConfigurationError, match="both"):
        build_tool_registry(settings, xray_importer=_Importer())
    with pytest.raises(ConfigurationError, match="both"):
        build_tool_registry(settings, xray_load_draft=lambda _id: None)


def test_invoke_tool_result_stays_opaque_json(env) -> None:
    from test.packs.software_delivery.tools.test_create_xray_tests import _draft

    importer = _Importer()
    invoke = InvokeTool(
        build_tool_registry(
            load_settings(), xray_importer=importer, xray_load_draft=lambda _id: _draft()
        )
    )

    response = invoke.execute(InvokeToolRequest(TOOL_NAME, {"draft_id": "draft-1"}))

    assert json.loads(response.result) == {
        "created_keys": ["QA-1"],
        "created_count": 1,
        "failed_count": 0,
    }
    assert importer.specs


def test_registry_passes_the_receipt_recorder_to_the_tool(env) -> None:
    from test.packs.software_delivery.tools.test_create_xray_tests import _draft

    recorded: list[tuple[str, tuple[str, ...]]] = []
    invoke = InvokeTool(
        build_tool_registry(
            load_settings(),
            xray_importer=_Importer(),
            xray_load_draft=lambda _id: _draft(),
            xray_on_created=lambda draft_id, keys: recorded.append((draft_id, keys)),
        )
    )

    invoke.execute(InvokeToolRequest(TOOL_NAME, {"draft_id": "draft-1"}))

    assert recorded == [("draft-1", ("QA-1",))]


def test_receipt_recorder_writes_where_the_test_design_page_reads(env) -> None:
    from composition.container import _workspace_store_path, _xray_receipt_recorder
    from composition.xray_export.receipt_store import VersionedXrayReceiptRepository
    from infrastructure.workspace_store.sql_store import VersionedWorkspaceStore

    _cloud(env)
    settings = load_settings()

    _xray_receipt_recorder(settings)("draft-1", ("QA-1", "QA-2"))

    repository = VersionedXrayReceiptRepository(
        VersionedWorkspaceStore(
            _workspace_store_path(settings), settings.document_catalog.workspace_id
        )
    )
    record = repository.get("draft-1")
    assert record is not None
    assert (record.project_key, record.created_keys) == ("QA", ("QA-1", "QA-2"))


def test_receipt_store_failure_does_not_fail_the_completed_create() -> None:
    from composition.xray_export.receipt_store import receipt_recorder

    class _BrokenRepository:
        def append(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("store down")

    receipt_recorder(_BrokenRepository(), project_key="QA")("draft-1", ("QA-1",))  # type: ignore[arg-type]


def test_build_invoke_tool_registers_xray_when_configured(env) -> None:
    from composition.container import build_invoke_tool

    _cloud(env)

    invoke = build_invoke_tool(load_settings())

    assert TOOL_NAME in invoke._registry  # noqa: SLF001 — registry seam for wiring


def test_build_invoke_tool_omits_xray_when_not_configured(env) -> None:
    from composition.container import build_invoke_tool

    invoke = build_invoke_tool(load_settings())

    assert TOOL_NAME not in invoke._registry  # noqa: SLF001


def test_build_invoke_tool_omits_xray_when_pack_disabled(env) -> None:
    from composition.container import build_invoke_tool

    _cloud(env)
    env.delenv("DOMAIN_TOOL_PACKS")

    invoke = build_invoke_tool(load_settings())

    assert TOOL_NAME not in invoke._registry  # noqa: SLF001


def test_build_invoke_tool_omits_xray_without_a_workspace(env) -> None:
    from composition.container import build_invoke_tool

    _cloud(env)
    env.delenv("DOCUMENT_CATALOG_WORKSPACE_ID")

    invoke = build_invoke_tool(load_settings())

    assert TOOL_NAME not in invoke._registry  # noqa: SLF001


def _agent_chat(env: pytest.MonkeyPatch) -> list[dict[str, object]]:
    from test.composition.test_container import _RecordingRewriteRetrieve, _sd_env

    _sd_env(env)
    env.setenv("SOFTWARE_DELIVERY_AGENT_LOOP", "true")
    env.setattr(
        "composition.container.build_rewrite_and_retrieve_knowledge",
        lambda settings, vector_store=None: _RecordingRewriteRetrieve([]),
    )
    wired: list[dict[str, object]] = []

    def _fake_orchestrate(agent: object, **kwargs: object):
        del agent
        wired.append(kwargs)
        return lambda **_kwargs: None

    env.setattr("composition.container.build_agent_orchestrate", _fake_orchestrate)
    return wired


def _xray_decision(ask: object):
    router = ask._ask._router  # noqa: SLF001 — routing seam for wiring
    return router.classify("create xray tests", conversation_id="conv-1")


def test_agent_chat_wires_xray_prepare_and_signal_when_configured(env) -> None:
    from composition.container import build_tool_augmented_ask
    from composition.xray_export.prepare import XrayDraftUnavailable
    from test.composition.test_container import _StubChat

    wired = _agent_chat(env)
    _cloud(env)

    ask = build_tool_augmented_ask(load_settings(), chat_model=_StubChat())

    [kwargs] = wired
    prepare_xray = kwargs["prepare_xray"]
    assert callable(prepare_xray)
    assert isinstance(prepare_xray("conv-without-draft"), XrayDraftUnavailable)
    decision = _xray_decision(ask)
    assert (decision.workflow_hint, decision.reason) == ("xray_export", "missing_fields")


def test_agent_chat_without_xray_has_no_prepare_and_signal_is_unavailable(env) -> None:
    from composition.container import build_tool_augmented_ask
    from test.composition.test_container import _StubChat

    wired = _agent_chat(env)

    ask = build_tool_augmented_ask(load_settings(), chat_model=_StubChat())

    [kwargs] = wired
    assert kwargs.get("prepare_xray") is None
    decision = _xray_decision(ask)
    assert (decision.workflow_hint, decision.reason) == ("xray_export", "tool_unavailable")


def test_xray_importer_matches_the_configured_deployment(env) -> None:
    from composition.xray_export.wiring import build_xray_importer
    from infrastructure.connectors.xray.cloud import XrayCloudImporter
    from infrastructure.connectors.xray.server import XrayServerImporter

    assert build_xray_importer(load_settings()) is None

    _cloud(env)
    assert isinstance(build_xray_importer(load_settings()), XrayCloudImporter)

    env.setenv("XRAY_DEPLOYMENT", "server")
    env.setenv("JIRA_DC_BASE_URL", "https://jira.example.test")
    env.setenv("JIRA_DC_TOKEN", "dc-token")
    assert isinstance(build_xray_importer(load_settings()), XrayServerImporter)
