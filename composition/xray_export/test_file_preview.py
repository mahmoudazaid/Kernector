"""MCP schemas and binding for ``software_delivery.preview_test_file_scenarios`` (#396).

Composition owns the strict argument and result schemas so the pack stays free
of pydantic. The tool is a pure parser: the binding carries only the
configured tag names, never a Jira/Xray client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator
from pydantic_core import PydanticCustomError

from composition.mcp.tool_registry import SAFE_VALIDATION_ERROR_TYPE, McpToolPrompt
from packs.software_delivery.limits import (
    MAX_TEST_FILE_BYTES,
    MAX_TEST_FILE_PATH_CHARS,
    MAX_TEST_FILES,
)
from packs.software_delivery.test_files.models import TestFileTagConfig

if TYPE_CHECKING:
    from infrastructure.config import Settings

_STRICT = ConfigDict(extra="forbid", strict=True)


class TestFileInput(BaseModel):
    """One caller-supplied file: workspace-relative path and full text."""

    __test__ = False
    model_config = _STRICT

    path: StrictStr = Field(
        min_length=1,
        max_length=MAX_TEST_FILE_PATH_CHARS,
        description="Workspace-relative path ending in .robot or .feature.",
    )
    content: StrictStr = Field(
        min_length=1,
        max_length=MAX_TEST_FILE_BYTES,
        description="Full file text as UTF-8.",
    )

    @field_validator("content")
    @classmethod
    def _content_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise PydanticCustomError(SAFE_VALIDATION_ERROR_TYPE, "File content must not be blank")
        return value


class PreviewTestFileScenariosArgs(BaseModel):
    """Arguments for ``software_delivery.preview_test_file_scenarios`` on MCP."""

    model_config = _STRICT

    files: list[TestFileInput] = Field(
        min_length=1,
        max_length=MAX_TEST_FILES,
        description="Robot Framework or Gherkin files to parse; nothing is read from disk.",
    )


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TagRolesOut(_Out):
    xray_key: str | None
    story_key: str | None
    candidate_keys: list[str]
    plain: list[str]


class ScenarioTagsOut(_Out):
    inherited: TagRolesOut
    local: TagRolesOut
    effective_plain: list[str]


class TableRowOut(_Out):
    line: int
    cells: list[str]


class DataTableOut(_Out):
    line: int
    rows: list[TableRowOut]


class DocStringOut(_Out):
    line: int
    delimiter: str
    media_type: str
    lines: list[str]
    indent: int


class StepOut(_Out):
    line: int
    keyword: str
    text: str
    arguments: list[str]
    data_table: DataTableOut | None
    doc_string: DocStringOut | None


class ExamplesOut(_Out):
    line: int
    keyword: str
    name: str
    tags: list[str]
    header: TableRowOut
    rows: list[TableRowOut]


class BackgroundOut(_Out):
    line: int
    name: str
    steps: list[StepOut]


class ScenarioOut(_Out):
    line: int
    keyword: str
    summary: str
    kind: Literal["manual", "cucumber"]
    outline: bool
    steps: list[StepOut]
    examples: list[ExamplesOut]
    tags: ScenarioTagsOut
    story_key: str | None
    xray_key: str | None


class TestFileOut(_Out):
    __test__ = False

    path: str
    format: Literal["robot", "gherkin"]
    story_key: str | None
    story_candidates: list[str]
    file_tags: TagRolesOut
    background: BackgroundOut | None
    scenarios: list[ScenarioOut]


class PreviewTestFileScenariosResult(_Out):
    """Parsed scenario specs per file; Jira/Xray is never contacted."""

    files: list[TestFileOut]
    scenario_count: int


PREVIEW_PROMPT_NAME = "preview_xray_scenarios"


def _render_preview_prompt(tool_name: str, file: str | None) -> str:
    target = (
        f"the file `{file}`"
        if file
        else "the .feature or .robot file open in the editor (or the one I mentioned)"
    )
    return (
        f"Preview the Xray scenarios of {target}. Read the file from the workspace "
        f"yourself, then call the `{tool_name}` tool with "
        '{"files": [{"path": <workspace-relative path>, "content": <exact full text>}]}. '
        "Send the content unchanged: do not reformat, trim or shorten it. Then list "
        "each scenario's line, summary, kind, story_key and xray_key, point out the "
        "scenarios without an xray_key, and show any validation_error message as returned."
    )


PREVIEW_PROMPT = McpToolPrompt(
    name=PREVIEW_PROMPT_NAME,
    description="Preview the Xray scenarios, keys and tags of a .feature or .robot file",
    argument="file",
    argument_description=(
        "Workspace-relative path of the .feature or .robot file; "
        "leave empty for the file open in the editor"
    ),
    render=_render_preview_prompt,
)


def _writeback_args_schema() -> type:
    from composition.xray_export.test_file_writeback import WriteXrayKeysToFilesArgs

    return WriteXrayKeysToFilesArgs


def _writeback_output_schema() -> type:
    from composition.xray_export.test_file_writeback import WriteXrayKeysToFilesResult

    return WriteXrayKeysToFilesResult


@dataclass(frozen=True, slots=True)
class TestFilePreviewMcpBinding:
    """Collaborators for the pack's ``build_mcp_tools(test_file_binding=...)``.

    It also serves the Xray key write-back tool (#399), which needs only tags.
    """

    __test__ = False

    tags: TestFileTagConfig
    args_schema: type = field(default=PreviewTestFileScenariosArgs)
    output_schema: type = field(default=PreviewTestFileScenariosResult)
    mcp_prompt: object = field(default=PREVIEW_PROMPT)
    writeback_args_schema: type = field(default_factory=_writeback_args_schema)
    writeback_output_schema: type = field(default_factory=_writeback_output_schema)


def build_test_file_tags(settings: Settings) -> TestFileTagConfig:
    """Return the tag names configured through ``XRAY_*`` settings."""
    xray = settings.xray
    return TestFileTagConfig(
        test_marker=xray.test_tag,
        story_marker=xray.story_tag,
        manual_tags=xray.manual_tags,
    )


def build_mcp_test_file_binding(settings: Settings) -> TestFilePreviewMcpBinding:
    """Return the binding; always available because the tool needs no client."""
    return TestFilePreviewMcpBinding(tags=build_test_file_tags(settings))
