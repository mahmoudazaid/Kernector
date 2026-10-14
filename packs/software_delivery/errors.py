"""Pack-local validation errors for the Software Delivery pack."""

import unicodedata
from enum import StrEnum

from domain.errors import (
    DomainValidationError,
    ToolArgumentValidationError,
    TrustedToolValidationError,
)

MAX_ERROR_PATH_CHARS = 120
_ELLIPSIS = "..."


class GoogleDriveExportValidationError(ToolArgumentValidationError):
    """Invalid caller arguments for Software Delivery Google Drive export."""


class XrayExportValidationError(ToolArgumentValidationError):
    """Invalid caller arguments for Software Delivery Xray test creation."""


class TestFilePreviewValidationError(ToolArgumentValidationError):
    """Malformed arguments for the test file scenario preview (#396)."""

    __test__ = False


class XrayKeyWritebackValidationError(ToolArgumentValidationError):
    """Malformed arguments for writing Xray keys back into test files (#399)."""


class OrchestrationValidationError(DomainValidationError):
    """Invalid Software Delivery chat tool selection."""


class TestFileErrorReason(StrEnum):
    """Fixed reasons a test file is rejected (#396); never include file content."""

    __test__ = False

    UNSUPPORTED_EXTENSION = "unsupported file type; expected .robot or .feature"
    FILE_TOO_LARGE = "file exceeds the size limit"
    TOO_MANY_FILES = "too many files in one call"
    TOTAL_TOO_LARGE = "files exceed the total size limit"
    TOO_MANY_SCENARIOS = "too many scenarios in one call"
    MISSING_FEATURE = "expected a Feature: before this line"
    DUPLICATE_FEATURE = "a file may contain only one Feature:"
    UNSUPPORTED_RULE = "Rule: is not supported"
    UNSUPPORTED_LANGUAGE = "only the English Gherkin dialect is supported"
    DUPLICATE_BACKGROUND = "a file may contain only one Background:"
    BACKGROUND_AFTER_SCENARIO = "Background: must come before the first scenario"
    DANGLING_TAGS = "tags must be followed by Feature:, a scenario or Examples:"
    MALFORMED_TAG = "every tag on a tag line must start with @"
    STEP_OUTSIDE_SCENARIO = "step must be inside a Background: or a scenario"
    ORPHAN_TABLE = "table rows must directly follow a step or an Examples: header"
    ORPHAN_DOC_STRING = "doc string must directly follow a step without a table"
    UNCLOSED_DOC_STRING = "doc string is not closed"
    MALFORMED_TABLE_ROW = "table row must start and end with |"
    INCONSISTENT_ROW_WIDTH = "table row has a different number of cells"
    EXAMPLES_OUTSIDE_OUTLINE = "Examples: must belong to a Scenario Outline:"
    OUTLINE_WITHOUT_EXAMPLES = "Scenario Outline: needs at least one Examples: table"
    EXAMPLES_WITHOUT_ROWS = "Examples: needs a header row and at least one data row"
    UNEXPECTED_LINE = "unexpected line; expected a step, table, doc string or keyword"
    EMPTY_SCENARIO_NAME = "scenario name is empty"
    LEADING_CONTINUATION = "... must continue a step or setting"
    CONFLICTING_XRAY_KEYS = "more than one Xray test key tag in the same scope"
    CONFLICTING_STORY_KEYS = "more than one story key tag in the same scope"
    FILE_LEVEL_XRAY_KEY = "an Xray test key tag is not allowed at file level"
    DUPLICATE_FILE_PATH = "the same file path was sent more than once"
    DUPLICATE_SCENARIO_SUMMARY = "another scenario without an Xray key has the same name"
    DUPLICATE_SCENARIO_NAME = "another scenario in this file has the same name"
    UNKNOWN_FILE = "an Xray key names a file that was not sent"
    UNKNOWN_SCENARIO = "an Xray key names a scenario that is not in this file"
    INVALID_XRAY_KEY = "the Xray key is not a Jira issue key"
    DUPLICATE_KEY_OWNER = "another scenario would carry the same Xray key"
    KEY_USED_AS_OTHER_TAG = (
        "the Xray key is already a story, file-level or another scenario's key tag"
    )
    PIPE_ROWS_UNSUPPORTED = "pipe-separated rows cannot be rewritten"
    COMMENTED_TAG_LINE = "a tag line with a # comment cannot be rewritten"
    ROLE_CHANGE = "writing the Xray key would change this scenario's other tags"
    RESULT_TOO_LARGE = "the rewritten files exceed the result size limit; send fewer files"


class TestFileValidationError(TrustedToolValidationError):
    """A test file was rejected; the message names the file and line (#396).

    The path is stripped of control characters and truncated to
    ``MAX_ERROR_PATH_CHARS``; the reason is fixed text.
    """

    __test__ = False

    def __init__(
        self, path: str | None, line: int | None, reason: TestFileErrorReason
    ) -> None:
        self.path = None if path is None else _safe_path(path)
        self.line = line
        self.reason = reason
        location = self.path or ""
        if location and line is not None:
            location = f"{location}:{line}"
        super().__init__(f"{location}: {reason.value}" if location else reason.value)


def _safe_path(path: str) -> str:
    cleaned = "".join(
        char for char in path if not unicodedata.category(char).startswith("C")
    )
    if len(cleaned) <= MAX_ERROR_PATH_CHARS:
        return cleaned
    return _ELLIPSIS + cleaned[-(MAX_ERROR_PATH_CHARS - len(_ELLIPSIS)) :]
