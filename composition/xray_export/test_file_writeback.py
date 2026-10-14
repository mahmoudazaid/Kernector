"""MCP schemas for ``software_delivery.write_xray_keys_to_files`` (#399).

Composition owns the strict argument and result schemas so the pack stays free
of pydantic. The tool shares the preview's tag-only binding: no Jira/Xray
client is ever wired.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from composition.xray_export.test_file_preview import TestFileInput
from packs.software_delivery.limits import MAX_TEST_FILE_SCENARIOS, MAX_TEST_FILES
from packs.software_delivery.test_files.tags import ISSUE_KEY

_STRICT = ConfigDict(extra="forbid", strict=True)

XrayKey = Annotated[StrictStr, Field(pattern=f"^{ISSUE_KEY.pattern}$")]


class WriteXrayKeysToFilesArgs(BaseModel):
    """Arguments for ``software_delivery.write_xray_keys_to_files`` on MCP."""

    model_config = _STRICT

    files: list[TestFileInput] = Field(
        min_length=1,
        max_length=MAX_TEST_FILES,
        description="Robot Framework or Gherkin files to tag; nothing is read from disk.",
    )
    keys: dict[Annotated[StrictStr, Field(min_length=1)], XrayKey] = Field(
        min_length=1,
        max_length=MAX_TEST_FILE_SCENARIOS,
        description=(
            "Maps '<path>::<scenario summary>' to the scenario's Xray test key, "
            "e.g. the create tool's created map."
        ),
    )


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WrittenFileOut(_Out):
    path: str
    changed: bool
    content: str
    diff: str


class WrittenScenarioOut(_Out):
    path: str
    line: int
    summary: str
    key: str
    previous_key: str | None
    status: Literal["TAGGED", "REPLACED", "NORMALIZED", "UNCHANGED"]


class WriteCountsOut(_Out):
    TAGGED: int
    REPLACED: int
    NORMALIZED: int
    UNCHANGED: int


class WriteXrayKeysToFilesResult(_Out):
    """Full rewritten text and unified diff per file; the caller applies them."""

    files: list[WrittenFileOut]
    results: list[WrittenScenarioOut]
    counts: WriteCountsOut
