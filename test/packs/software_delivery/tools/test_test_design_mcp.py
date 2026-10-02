"""Tests for the Software Delivery Test Design MCP tools (#338)."""

from __future__ import annotations

import json

import pytest

from packs.software_delivery.tools.test_design_mcp import (
    TEST_DESIGN_MCP_TOOLS,
    TOOL_CONFIRM,
    TOOL_EXPORT_FEATURE,
    TOOL_GENERATE,
    TOOL_GET,
    TOOL_START,
    TestDesignConfirmTool,
    TestDesignExportFeatureTool,
    TestDesignGenerateTool,
    TestDesignGetTool,
    TestDesignStartTool,
)

_RESULT = {"draft_id": "draft-1", "version": 1, "candidates": []}


class _StartArgs: ...


class _GetArgs: ...


class _ConfirmArgs: ...


class _GenerateArgs: ...


class _ExportFeatureArgs: ...


class _Result: ...


class _FeatureFileResult: ...


class _FakeWorkflow:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.error: Exception | None = None

    def _record(self, name: str, arguments) -> dict[str, object]:
        self.calls.append((name, dict(arguments)))
        if self.error is not None:
            raise self.error
        return _RESULT

    def start(self, arguments):
        return self._record("start", arguments)

    def get(self, arguments):
        return self._record("get", arguments)

    def confirm(self, arguments):
        return self._record("confirm", arguments)

    def generate(self, arguments):
        return self._record("generate", arguments)

    def export_feature(self, arguments):
        return self._record("export_feature", arguments)


class _FakeBinding:
    start_args = _StartArgs
    get_args = _GetArgs
    confirm_args = _ConfirmArgs
    generate_args = _GenerateArgs
    export_feature_args = _ExportFeatureArgs
    result = _Result
    feature_file_result = _FeatureFileResult

    def __init__(self, factory=None) -> None:
        self.workflow_instance = _FakeWorkflow()
        self._factory = factory or (lambda: self.workflow_instance)

    def workflow(self):
        return self._factory()


def test_tool_ids_are_stable() -> None:
    assert TOOL_START == "software_delivery.test_design_start"
    assert TOOL_GET == "software_delivery.test_design_get"
    assert TOOL_CONFIRM == "software_delivery.test_design_confirm"
    assert TOOL_GENERATE == "software_delivery.test_design_generate"
    assert TOOL_EXPORT_FEATURE == "software_delivery.test_design_export_feature"
    binding = _FakeBinding()
    assert [(tool_id, cls(binding).name) for tool_id, cls in TEST_DESIGN_MCP_TOOLS] == [
        (TOOL_START, TOOL_START),
        (TOOL_GET, TOOL_GET),
        (TOOL_CONFIRM, TOOL_CONFIRM),
        (TOOL_GENERATE, TOOL_GENERATE),
        (TOOL_EXPORT_FEATURE, TOOL_EXPORT_FEATURE),
    ]


@pytest.mark.parametrize(
    ("tool_cls", "operation", "args_schema", "output_schema"),
    [
        (TestDesignStartTool, "start", _StartArgs, _Result),
        (TestDesignGetTool, "get", _GetArgs, _Result),
        (TestDesignConfirmTool, "confirm", _ConfirmArgs, _Result),
        (TestDesignGenerateTool, "generate", _GenerateArgs, _Result),
        (
            TestDesignExportFeatureTool,
            "export_feature",
            _ExportFeatureArgs,
            _FeatureFileResult,
        ),
    ],
)
def test_tool_uses_binding_schemas_and_dispatches_raw_arguments(
    tool_cls, operation: str, args_schema: type, output_schema: type
) -> None:
    binding = _FakeBinding()
    tool = tool_cls(binding)
    arguments = {"draft_id": "draft-1", "expected_version": 2}

    raw = tool.run(arguments)

    assert tool.args_schema is args_schema
    assert tool.output_schema is output_schema
    assert binding.workflow_instance.calls == [(operation, arguments)]
    assert json.loads(raw) == _RESULT


def test_workflow_errors_propagate_unchanged() -> None:
    class _Boom(RuntimeError):
        pass

    binding = _FakeBinding()
    error = _Boom("internal detail")
    binding.workflow_instance.error = error

    with pytest.raises(_Boom) as caught:
        TestDesignGetTool(binding).run({"draft_id": "draft-1"})

    assert caught.value is error


def test_workflow_is_built_per_invocation() -> None:
    created: list[_FakeWorkflow] = []

    def factory() -> _FakeWorkflow:
        workflow = _FakeWorkflow()
        created.append(workflow)
        return workflow

    tool = TestDesignGetTool(_FakeBinding(factory))
    assert created == []
    tool.run({"draft_id": "draft-1"})
    tool.run({"draft_id": "draft-1"})

    assert len(created) == 2
