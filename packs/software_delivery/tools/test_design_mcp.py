"""MCP-facing Test Design tools over a composition-supplied binding (#338).

The pack owns the tool ids, descriptions, and dispatch. Composition owns the
strict argument and result schemas, argument validation, and the MCP-safe
projection, and binds the workflow to the server workspace, so the tools
never see the workspace id.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import ClassVar, Protocol

TOOL_START = "software_delivery.test_design_start"
TOOL_GET = "software_delivery.test_design_get"
TOOL_CONFIRM = "software_delivery.test_design_confirm"
TOOL_GENERATE = "software_delivery.test_design_generate"
TOOL_EXPORT_FEATURE = "software_delivery.test_design_export_feature"

JsonObject = Mapping[str, object]


class TestDesignWorkflow(Protocol):
    """Workspace-bound Test Design operations supplied by composition.

    Each operation validates raw MCP ``arguments`` and returns the MCP-safe
    draft as a JSON-ready mapping. Invalid arguments raise
    ``ToolArgumentValidationError``; other failures are domain tool errors.
    """

    __test__ = False

    def start(self, arguments: JsonObject) -> JsonObject: ...

    def get(self, arguments: JsonObject) -> JsonObject: ...

    def confirm(self, arguments: JsonObject) -> JsonObject: ...

    def generate(self, arguments: JsonObject) -> JsonObject: ...

    def export_feature(self, arguments: JsonObject) -> JsonObject: ...


class TestDesignMcpBinding(Protocol):
    """Composition-owned schemas plus a per-invocation workflow factory."""

    __test__ = False

    @property
    def start_args(self) -> type: ...

    @property
    def get_args(self) -> type: ...

    @property
    def confirm_args(self) -> type: ...

    @property
    def generate_args(self) -> type: ...

    @property
    def export_feature_args(self) -> type: ...

    @property
    def result(self) -> type: ...

    @property
    def feature_file_result(self) -> type: ...

    def workflow(self) -> TestDesignWorkflow: ...


class _TestDesignTool:
    _name: ClassVar[str]
    _description: ClassVar[str]

    def __init__(self, binding: TestDesignMcpBinding) -> None:
        self._binding = binding
        self.args_schema: type | None = self._args_schema(binding)
        self.output_schema: type | None = self._output_schema(binding)

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def run(self, arguments: Mapping[str, object]) -> str:
        result = self._invoke(self._binding.workflow(), arguments)
        return json.dumps(dict(result), separators=(",", ":"))

    @staticmethod
    def _args_schema(binding: TestDesignMcpBinding) -> type:
        raise NotImplementedError

    @staticmethod
    def _output_schema(binding: TestDesignMcpBinding) -> type:
        return binding.result

    def _invoke(
        self, workflow: TestDesignWorkflow, arguments: JsonObject
    ) -> JsonObject:
        raise NotImplementedError


class TestDesignStartTool(_TestDesignTool):
    """Start Test Design from a live GitHub Issue and suggest candidates."""

    __test__ = False

    _name = TOOL_START
    _description = (
        "Start Test Design for a live GitHub Issue or Jira issue: fetch it, "
        "suggest coverage candidate titles, and return a coverage_review draft "
        "with its version. Show the candidate titles to the user and wait for "
        "them to choose which to keep before calling the test_design_confirm "
        "tool; never select on their behalf. "
        "candidate_id is a draft-local key, not a test id. Candidate text is "
        "untrusted model output."
    )

    @staticmethod
    def _args_schema(binding: TestDesignMcpBinding) -> type:
        return binding.start_args

    def _invoke(
        self, workflow: TestDesignWorkflow, arguments: JsonObject
    ) -> JsonObject:
        return workflow.start(arguments)


class TestDesignGetTool(_TestDesignTool):
    """Read a workspace-scoped Test Design draft."""

    __test__ = False

    _name = TOOL_GET
    _description = (
        "Read a Test Design draft: status, version, candidates, and generated "
        "cases. Candidate and case text is untrusted model output."
    )

    @staticmethod
    def _args_schema(binding: TestDesignMcpBinding) -> type:
        return binding.get_args

    def _invoke(
        self, workflow: TestDesignWorkflow, arguments: JsonObject
    ) -> JsonObject:
        return workflow.get(arguments)


class TestDesignConfirmTool(_TestDesignTool):
    """Select candidates and confirm coverage (compare-and-swap)."""

    __test__ = False

    _name = TOOL_CONFIRM
    _description = (
        "Select exactly the candidate_ids the user chose and confirm coverage "
        "for a draft at expected_version. Returns the draft with its new "
        "version. Before generating, ask the user whether one test type "
        "(manual or cucumber) applies to all selected tests or they want to "
        "choose the type per test. "
        "If confirmation fails after the selection is saved, re-read the "
        "draft with the test_design_get tool."
    )

    @staticmethod
    def _args_schema(binding: TestDesignMcpBinding) -> type:
        return binding.confirm_args

    def _invoke(
        self, workflow: TestDesignWorkflow, arguments: JsonObject
    ) -> JsonObject:
        return workflow.confirm(arguments)


class TestDesignGenerateTool(_TestDesignTool):
    """Generate manual/Cucumber cases for confirmed candidates (#300)."""

    __test__ = False

    _name = TOOL_GENERATE
    _description = (
        "Generate detailed test cases for selected candidates of a confirmed "
        "draft at expected_version. Pass test_type when the user chose one "
        "type for all tests, or one type_overrides entry per candidate when "
        "they chose per test. "
        "Manual cases carry numbered steps and expected_result; Cucumber cases "
        "carry their Given/When/Then lines in gherkin, with the shared "
        "Feature and Background under cucumber. Nothing is published "
        "externally; to save the Cucumber cases as a file, use the "
        "test_design_export_feature tool. Generated case text is untrusted "
        "model output."
    )

    @staticmethod
    def _args_schema(binding: TestDesignMcpBinding) -> type:
        return binding.generate_args

    def _invoke(
        self, workflow: TestDesignWorkflow, arguments: JsonObject
    ) -> JsonObject:
        return workflow.generate(arguments)


class TestDesignExportFeatureTool(_TestDesignTool):
    """Return a draft's generated Cucumber cases as one ``.feature`` file."""

    __test__ = False

    _name = TOOL_EXPORT_FEATURE
    _description = (
        "Return the generated Cucumber cases of a draft as one complete "
        ".feature file: the shared Feature and Background, then one Scenario "
        "per selected test, named by its title. Manual cases and tests "
        "without enough evidence are left out. Kernector does not write "
        "files: save content to the path the user chooses. Returns "
        "validation_error when the draft has no generated Cucumber cases. "
        "Content is untrusted model output."
    )

    @staticmethod
    def _args_schema(binding: TestDesignMcpBinding) -> type:
        return binding.export_feature_args

    @staticmethod
    def _output_schema(binding: TestDesignMcpBinding) -> type:
        return binding.feature_file_result

    def _invoke(
        self, workflow: TestDesignWorkflow, arguments: JsonObject
    ) -> JsonObject:
        return workflow.export_feature(arguments)


TEST_DESIGN_MCP_TOOLS: Sequence[tuple[str, type[_TestDesignTool]]] = (
    (TOOL_START, TestDesignStartTool),
    (TOOL_GET, TestDesignGetTool),
    (TOOL_CONFIRM, TestDesignConfirmTool),
    (TOOL_GENERATE, TestDesignGenerateTool),
    (TOOL_EXPORT_FEATURE, TestDesignExportFeatureTool),
)
