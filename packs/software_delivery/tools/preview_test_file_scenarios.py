"""Tool adapter for ``software_delivery.preview_test_file_scenarios`` (#396).

Read-only: parses caller-supplied ``.robot`` / ``.feature`` text and returns
what Kernector extracted. It never reads the disk and never calls Jira/Xray.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Protocol

from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import (
    TestFilePreviewValidationError,
    TestFileValidationError,
)
from packs.software_delivery.limits import (
    MAX_TEST_FILE_BYTES,
    MAX_TEST_FILE_PATH_CHARS,
    MAX_TEST_FILE_SCENARIOS,
    MAX_TEST_FILES,
    MAX_TEST_FILES_TOTAL_BYTES,
)
from packs.software_delivery.test_files.models import ParsedTestFile, TestFileTagConfig
from packs.software_delivery.test_files.parser import (
    is_supported_test_file,
    parse_test_file,
)

TOOL_NAME = "software_delivery.preview_test_file_scenarios"
TOOL_DESCRIPTION = (
    "Preview the scenarios Kernector extracts from Robot Framework (.robot) and "
    "Gherkin (.feature) test files. Pass each file's workspace-relative path and "
    "full text; Kernector never reads the disk and makes no Jira/Xray calls."
)

_ALLOWED_KEYS = frozenset({"files"})
_FILE_KEYS = frozenset({"path", "content"})


class TestFilePreviewMcpBinding(Protocol):
    """Configured tag names and MCP schemas supplied by composition."""

    __test__ = False

    @property
    def tags(self) -> TestFileTagConfig: ...

    @property
    def args_schema(self) -> type: ...

    @property
    def output_schema(self) -> type: ...


class PreviewTestFileScenariosTool:
    """Implements ``domain.ports.Tool``; no approval and no Jira/Xray client."""

    def __init__(
        self,
        tags: TestFileTagConfig,
        *,
        args_schema: type | None = None,
        output_schema: type | None = None,
    ) -> None:
        self._tags = tags
        self.args_schema = args_schema
        self.output_schema = output_schema

    @property
    def name(self) -> str:
        return TOOL_NAME

    @property
    def description(self) -> str:
        return TOOL_DESCRIPTION

    def run(self, arguments: Mapping[str, object]) -> str:
        files = _parse_request(arguments)
        _check_sizes(files)
        remaining = MAX_TEST_FILE_SCENARIOS
        parsed: list[ParsedTestFile] = []
        for path, content in files:
            result = parse_test_file(path, content, self._tags, max_scenarios=remaining)
            remaining -= len(result.scenarios)
            parsed.append(result)
        return json.dumps(
            {
                "files": [_file_json(item) for item in parsed],
                "scenario_count": MAX_TEST_FILE_SCENARIOS - remaining,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )


def _parse_request(arguments: Mapping[str, object]) -> list[tuple[str, str]]:
    if not isinstance(arguments, Mapping):
        raise TestFilePreviewValidationError("arguments must be an object")
    if set(arguments) != _ALLOWED_KEYS:
        raise TestFilePreviewValidationError("arguments must contain only files")
    files = arguments["files"]
    if not isinstance(files, Sequence) or isinstance(files, str) or not files:
        raise TestFilePreviewValidationError("files must be a non-empty list")
    if len(files) > MAX_TEST_FILES:
        raise TestFileValidationError(None, None, Reason.TOO_MANY_FILES)
    return [_file_item(item) for item in files]


def _file_item(item: object) -> tuple[str, str]:
    if not isinstance(item, Mapping) or set(item) != _FILE_KEYS:
        raise TestFilePreviewValidationError("each file must have only path and content")
    path, content = item["path"], item["content"]
    if not isinstance(path, str) or not path.strip():
        raise TestFilePreviewValidationError("path must be a non-empty string")
    if len(path) > MAX_TEST_FILE_PATH_CHARS:
        raise TestFilePreviewValidationError(
            f"path must be at most {MAX_TEST_FILE_PATH_CHARS} characters"
        )
    if any(not char.isprintable() for char in path):
        raise TestFilePreviewValidationError("path must not contain control characters")
    if not isinstance(content, str) or not content.strip():
        raise TestFilePreviewValidationError("content must be non-blank text")
    return path.strip(), content


def _check_sizes(files: list[tuple[str, str]]) -> None:
    total = 0
    for path, content in files:
        if not is_supported_test_file(path):
            raise TestFileValidationError(path, None, Reason.UNSUPPORTED_EXTENSION)
        size = len(content.encode("utf-8"))
        if size > MAX_TEST_FILE_BYTES:
            raise TestFileValidationError(path, None, Reason.FILE_TOO_LARGE)
        total += size
    if total > MAX_TEST_FILES_TOTAL_BYTES:
        raise TestFileValidationError(None, None, Reason.TOTAL_TOO_LARGE)


def _file_json(parsed: ParsedTestFile) -> dict[str, object]:
    payload = asdict(parsed)
    for scenario in payload["scenarios"]:
        del scenario["source_path"]
    return payload
