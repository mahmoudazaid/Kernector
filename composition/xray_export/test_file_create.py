"""MCP schemas and binding for ``software_delivery.create_xray_tests_from_files`` (#397).

Composition owns the strict argument and result schemas so the pack stays free
of pydantic. One binding serves chat and MCP; every call needs approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from composition.xray_export.test_file_preview import TestFileInput, build_test_file_tags
from packs.software_delivery.limits import MAX_TEST_FILES

if TYPE_CHECKING:
    from domain.ports import XrayIssueLookup, XrayTestImporter
    from infrastructure.config import Settings
    from packs.software_delivery.test_files.models import TestFileTagConfig


class CreateXrayTestsFromFilesArgs(BaseModel):
    """Arguments for ``software_delivery.create_xray_tests_from_files`` on MCP."""

    model_config = ConfigDict(extra="forbid", strict=True)

    files: list[TestFileInput] = Field(
        min_length=1,
        max_length=MAX_TEST_FILES,
        description="Robot Framework or Gherkin files; nothing is read from disk.",
    )
    dry_run: StrictBool = Field(
        default=False,
        description="Plan only: report what would be created without changing Jira.",
    )


Status = Literal["CREATED", "WOULD_CREATE", "EXISTS_UNTAGGED", "AMBIGUOUS", "NO_STORY", "ERROR"]
Reason = Literal[
    "issue_unresolved",
    "issue_not_found",
    "multiple_tests",
    "test_key_claimed",
    "repeated_in_run",
    "no_story",
    "story_not_found",
    "story_unresolved",
    "not_a_story",
    "assertion_without_action",
    "manual_outline_unsupported",
    "manual_unsupported",
    "cucumber_unsupported",
    "outline_unsupported",
    "link_unsupported",
    "required_fields",
    "rejected",
    "auth_failed",
    "outcome_unknown",
    "not_attempted",
    "link_not_confirmed",
    "outline_not_confirmed",
]
StopReason = Literal["auth_failed", "outcome_unknown", "link_not_confirmed", "outline_not_confirmed"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioResultOut(_Out):
    path: str
    line: int
    summary: str
    status: Status
    key: str | None
    candidate_keys: list[str]
    story_key: str | None
    reason: Reason | None


class StatusCountsOut(_Out):
    CREATED: int
    WOULD_CREATE: int
    EXISTS_UNTAGGED: int
    AMBIGUOUS: int
    NO_STORY: int
    ERROR: int


class CreateXrayTestsFromFilesResult(_Out):
    """Per-scenario outcome; ``created`` maps ``path::scenario`` to the new key."""

    results: list[ScenarioResultOut]
    created: dict[str, str]
    dry_run: bool
    counts: StatusCountsOut
    stopped: bool
    stop_reason: StopReason | None


@dataclass(frozen=True, slots=True)
class XrayFileCreateBinding:
    """Collaborators for the pack's ``xray_file_binding`` (chat and MCP)."""

    importer: XrayTestImporter
    lookup: XrayIssueLookup
    tags: TestFileTagConfig
    project_key: str
    story_issue_types: frozenset[str]
    default_component: str | None = None
    args_schema: type | None = field(default=CreateXrayTestsFromFilesArgs)
    output_schema: type | None = field(default=CreateXrayTestsFromFilesResult)


def build_xray_file_create_binding(settings: Settings) -> XrayFileCreateBinding | None:
    """Return the binding, or ``None`` when Xray is not configured."""
    from composition.xray_export.wiring import build_xray_importer

    client = build_xray_importer(settings)
    if client is None:
        return None
    xray = settings.xray
    return XrayFileCreateBinding(
        importer=client,
        lookup=client,
        tags=build_test_file_tags(settings),
        project_key=xray.project_key or "",
        story_issue_types=frozenset(xray.story_issue_types),
        default_component=xray.default_component,
    )
