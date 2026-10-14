"""MCP schemas and binding for ``software_delivery.create_xray_tests_from_files`` (#397).

Composition owns the strict argument and result schemas so the pack stays free
of pydantic. One binding serves chat and MCP for creating (#397) and updating
(#398) tests from files; every call needs approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from composition.xray_export.test_file_preview import TestFileInput, build_test_file_tags
from composition.xray_export.test_file_pull import (
    PullXrayTestsToFilesArgs,
    PullXrayTestsToFilesResult,
)
from composition.xray_export.test_file_update import (
    UpdateXrayTestsFromFilesArgs,
    UpdateXrayTestsFromFilesResult,
)
from packs.software_delivery.limits import MAX_TEST_FILES

if TYPE_CHECKING:
    from domain.ports import XrayIssueLookup, XrayTestImporter, XrayTestUpdater
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

    destination: str | None
    results: list[ScenarioResultOut]
    created: dict[str, str]
    dry_run: bool
    counts: StatusCountsOut
    stopped: bool
    stop_reason: StopReason | None


class XrayTargetArgs(BaseModel):
    """``software_delivery.xray_target`` takes no arguments."""

    model_config = ConfigDict(extra="forbid", strict=True)


class XrayTargetResult(_Out):
    """The checked Xray destination and what its project supports."""

    project_key: str
    destination: str
    supports_manual: bool
    supports_cucumber: bool
    supports_cucumber_outline: bool
    supports_issue_link: bool


@dataclass(frozen=True, slots=True)
class XrayFileCreateBinding:
    """Collaborators for the pack's ``xray_file_binding`` (chat and MCP)."""

    importer: XrayTestImporter
    lookup: XrayIssueLookup
    updater: XrayTestUpdater
    tags: TestFileTagConfig
    project_key: str
    destination_label: str
    story_issue_types: frozenset[str]
    link_type: str
    link_direction: str = "outward"
    default_component: str | None = None
    new_file_name_template: str = "{epic_summary}__{story_summary}"
    args_schema: type | None = field(default=CreateXrayTestsFromFilesArgs)
    output_schema: type | None = field(default=CreateXrayTestsFromFilesResult)
    target_args_schema: type | None = field(default=XrayTargetArgs)
    target_output_schema: type | None = field(default=XrayTargetResult)
    update_args_schema: type | None = field(default=UpdateXrayTestsFromFilesArgs)
    update_output_schema: type | None = field(default=UpdateXrayTestsFromFilesResult)
    pull_args_schema: type | None = field(default=PullXrayTestsToFilesArgs)
    pull_output_schema: type | None = field(default=PullXrayTestsToFilesResult)


def build_xray_file_create_binding(settings: Settings) -> XrayFileCreateBinding | None:
    """Return the binding, or ``None`` when Xray is not configured."""
    from composition.xray_export.wiring import build_xray_importer

    client = build_xray_importer(settings)
    if client is None:
        return None
    xray = settings.xray
    project_key = xray.project_key or ""
    return XrayFileCreateBinding(
        importer=client,
        lookup=client,
        updater=client,
        tags=build_test_file_tags(settings),
        project_key=project_key,
        destination_label=xray_destination_label(settings, project_key),
        story_issue_types=frozenset(xray.story_issue_types),
        link_type=xray.link_type,
        link_direction=xray.link_direction,
        default_component=xray.default_component,
        new_file_name_template=xray.new_file_name_template,
    )


def xray_destination_label(settings: Settings, project_key: str) -> str:
    """Name the project and Jira instance tests are created in; never credentials."""
    jira = settings.jira_data_center
    if settings.xray.deployment == "server" and jira is not None and jira.base_url:
        host = urlparse(jira.base_url).hostname
        if host:
            return f"Jira project {project_key} on {host}"
    return f"Jira project {project_key} (Xray Cloud)"
