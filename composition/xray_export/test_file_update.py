"""MCP schemas for ``software_delivery.update_xray_tests_from_files`` (#398).

Composition owns the strict argument and result schemas so the pack stays free
of pydantic. The tool shares ``XrayFileCreateBinding`` with #397; every call
needs approval. A real run reports ``UPDATED``, ``SKIPPED`` or ``ERROR``; a dry
run reports ``WOULD_UPDATE`` in place of ``UPDATED``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from composition.xray_export.test_file_preview import TestFileInput
from packs.software_delivery.limits import MAX_TEST_FILES


class UpdateXrayTestsFromFilesArgs(BaseModel):
    """Arguments for ``software_delivery.update_xray_tests_from_files`` on MCP."""

    model_config = ConfigDict(extra="forbid", strict=True)

    files: list[TestFileInput] = Field(
        min_length=1,
        max_length=MAX_TEST_FILES,
        description="Robot Framework or Gherkin files; nothing is read from disk.",
    )
    dry_run: StrictBool = Field(
        default=False,
        description="Plan only: report what would be updated without changing Jira.",
    )


Status = Literal["UPDATED", "WOULD_UPDATE", "SKIPPED", "ERROR"]
StoryProblem = Literal["no_story", "story_not_found", "story_unresolved", "not_a_story"]
Reason = Literal[
    "not_found",
    "ambiguous",
    "test_key_claimed",
    "issue_not_found",
    "issue_unresolved",
    "not_a_test",
    "no_story",
    "story_not_found",
    "story_unresolved",
    "not_a_story",
    "assertion_without_action",
    "manual_outline_unsupported",
    "details_missing",
    "details_unreadable",
    "other_project",
    "unsupported_test_type",
    "jira_fields_unsupported",
    "field_not_editable",
    "component_not_allowed",
    "link_type_unavailable",
    "type_change_drops_preconditions",
    "rejected",
    "auth_failed",
    "outcome_unknown",
    "partially_applied",
    "not_confirmed",
    "not_attempted",
]
Change = Literal[
    "summary", "test_type", "scenario_type", "steps", "gherkin", "component", "story_link"
]
StopReason = Literal["auth_failed", "outcome_unknown", "partially_applied", "not_confirmed"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UpdateScenarioResultOut(_Out):
    path: str
    line: int
    summary: str
    status: Status
    key: str | None
    candidate_keys: list[str]
    story_key: str | None
    story_problem: StoryProblem | None
    changes: list[Change]
    reason: Reason | None


class UpdateStatusCountsOut(_Out):
    UPDATED: int
    WOULD_UPDATE: int
    SKIPPED: int
    ERROR: int


class UpdateXrayTestsFromFilesResult(_Out):
    """Per-scenario outcome; ``changes`` names the fields sent (or planned)."""

    destination: str | None
    results: list[UpdateScenarioResultOut]
    dry_run: bool
    counts: UpdateStatusCountsOut
    stopped: bool
    stop_reason: StopReason | None
