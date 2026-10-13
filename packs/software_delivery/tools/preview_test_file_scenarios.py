"""Tool adapter for ``software_delivery.preview_test_file_scenarios`` (#396).

Read-only: parses caller-supplied ``.robot`` / ``.feature`` text and returns
what Kernector extracted. It never reads the disk and never calls Jira/Xray.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Protocol

from packs.software_delivery.errors import TestFilePreviewValidationError
from packs.software_delivery.test_files.models import ParsedTestFile, TestFileTagConfig
from packs.software_delivery.test_files.request import parse_files, read_files

TOOL_NAME = "software_delivery.preview_test_file_scenarios"
TOOL_DESCRIPTION = (
    "Preview the scenarios, Xray test keys, story keys and tags Kernector extracts "
    "from Cucumber/Gherkin (.feature) and Robot Framework (.robot) test files, and "
    "report syntax or tagging problems with file and line. Use it when the user asks "
    "to check, preview or validate a test file, e.g. 'what will go to Xray from this "
    "feature?', 'check the tags in this file' or 'which scenarios have no Xray key?'. "
    "When the user means the file open in the editor or a file they mention, read it "
    "from the workspace yourself and pass its workspace-relative path and exact full "
    "text, unchanged; do not ask the user for the path. Several files may be sent in "
    "one call. Kernector never reads the disk and makes no Jira/Xray calls."
)

_ALLOWED_KEYS = frozenset({"files"})


class TestFilePreviewMcpBinding(Protocol):
    """Configured tag names and MCP schemas supplied by composition."""

    __test__ = False

    @property
    def tags(self) -> TestFileTagConfig: ...

    @property
    def args_schema(self) -> type: ...

    @property
    def output_schema(self) -> type: ...

    @property
    def mcp_prompt(self) -> object: ...


class PreviewTestFileScenariosTool:
    """Implements ``domain.ports.Tool``; no approval and no Jira/Xray client."""

    def __init__(
        self,
        tags: TestFileTagConfig,
        *,
        args_schema: type | None = None,
        output_schema: type | None = None,
        mcp_prompt: object | None = None,
    ) -> None:
        self._tags = tags
        self.args_schema = args_schema
        self.output_schema = output_schema
        self.mcp_prompt = mcp_prompt

    @property
    def name(self) -> str:
        return TOOL_NAME

    @property
    def description(self) -> str:
        return TOOL_DESCRIPTION

    def run(self, arguments: Mapping[str, object]) -> str:
        if not isinstance(arguments, Mapping):
            raise TestFilePreviewValidationError("arguments must be an object")
        if set(arguments) != _ALLOWED_KEYS:
            raise TestFilePreviewValidationError("arguments must contain only files")
        files = read_files(arguments["files"], TestFilePreviewValidationError)
        parsed = parse_files(files, self._tags)
        return json.dumps(
            {
                "files": [_file_json(item) for item in parsed],
                "scenario_count": sum(len(item.scenarios) for item in parsed),
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )


def _file_json(parsed: ParsedTestFile) -> dict[str, object]:
    payload = asdict(parsed)
    for scenario in payload["scenarios"]:
        del scenario["source_path"]
    return payload
