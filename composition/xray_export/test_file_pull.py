"""MCP schemas for ``software_delivery.pull_xray_tests_to_files`` (#400)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from composition.xray_export.test_file_preview import TestFileInput
from packs.software_delivery.limits import MAX_TEST_FILES

PullFormat = Literal["robot", "feature"]
PullStatus = Literal[
    "ADD",
    "WOULD_ADD",
    "BACKFILL_TAG",
    "WOULD_BACKFILL_TAG",
    "NEW_FILE",
    "WOULD_NEW_FILE",
    "SKIP_KNOWN",
    "SKIP_NO_STORY",
    "STORY_UNRESOLVED",
    "STORY_MISSING",
    "STORY_NOT_QUALIFYING",
    "STORY_AMBIGUOUS",
    "STORY_LINK_UNCONFIRMED",
    "UNREADABLE",
    "UNSUPPORTED",
    "KEY_CONFLICT",
    "LOCAL_AMBIGUOUS",
    "REMOTE_AMBIGUOUS",
    "TARGET_AMBIGUOUS",
    "PATH_COLLISION",
    "NAMING_FAILED",
    "LIMIT_EXCEEDED",
]


class PullXrayTestsToFilesArgs(BaseModel):
    """Arguments for ``software_delivery.pull_xray_tests_to_files`` on MCP."""

    model_config = ConfigDict(extra="forbid", strict=True)

    story_key: str | None = Field(
        default=None,
        description="Pull tests linked to this story. Mutually exclusive with project=true.",
    )
    project: StrictBool | None = Field(
        default=None,
        description="When true, pull all tests in the configured Xray project.",
    )
    component: str | None = Field(
        default=None,
        description="Project scope only. Omitted uses XRAY_DEFAULT_COMPONENT; null disables it.",
    )
    files: list[TestFileInput] = Field(
        default_factory=list,
        max_length=MAX_TEST_FILES,
        description="Existing .robot/.feature path+content inventory; may be empty.",
    )
    formats: list[PullFormat] = Field(
        default_factory=lambda: ["robot"],
        min_length=1,
        description="Target formats; robot and/or feature, unique.",
    )
    dry_run: StrictBool = Field(
        default=False,
        description="Same resolution as a normal run; omit file content and diffs.",
    )
    new_file_name_template: str | None = Field(
        default=None,
        description=(
            "Optional override of XRAY_NEW_FILE_NAME_TEMPLATE for this call. "
            "Only used when no existing story-tagged file matches."
        ),
    )
    new_file_paths: dict[str, str] | None = Field(
        default=None,
        description=(
            "Optional map of story_key to relative path for suggested new files. "
            "Ignored when an existing inventory file already matches that story."
        ),
    )


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PullTestFormatResultOut(_Out):
    key: str
    summary: str
    format: PullFormat
    status: PullStatus
    reason: str | None = None
    story_key: str | None = None
    path: str | None = None
    line: int | None = None
    candidate_keys: list[str] = Field(default_factory=list)
    candidate_identities: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PullFileProposalOut(_Out):
    path: str
    content: str
    diff: str
    changed: StrictBool = True


class PullScopeOut(_Out):
    kind: Literal["story", "project"]
    story_key: str | None = None
    project_key: str | None = None
    component: str | None = None


class PullXrayTestsToFilesResult(_Out):
    dry_run: StrictBool
    scope: PullScopeOut
    counts: dict[str, int]
    results: list[PullTestFormatResultOut]
    files: list[PullFileProposalOut]
