"""Server-side prepared call for agent Xray test creation (#199).

Binds ``software_delivery.create_xray_tests`` to the conversation's Test Design
draft. The agent never supplies the draft id; the approval card shows the
target project and how many tests would be created.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

# Composition-local constant — avoid importing the pack at module load.
TOOL_NAME = "software_delivery.create_xray_tests"
# Fixed runner target for a ready ``xray_export`` turn; the agent routes on it.
XRAY_EXPORT_TARGET = "Create Xray tests from the selected Test Design test cases"


class _DraftRepository(Protocol):
    def find_by_conversation_id(self, conversation_id: str) -> object | None:
        """Return the draft for ``conversation_id``, or ``None``."""


@dataclass(frozen=True, slots=True)
class XrayDraftUnavailable:
    """No draft, or no available generated case for a selected candidate."""


@dataclass(frozen=True, slots=True)
class PreparedXrayExportCall:
    """Closed-over Xray Tool invocation ready for the agent BoundTool."""

    tool_name: str
    arguments: Mapping[str, object]
    project_key: str
    test_count: int


def prepare_xray_export_call(
    *,
    conversation_id: str,
    drafts: _DraftRepository,
    project_key: str,
) -> PreparedXrayExportCall | XrayDraftUnavailable:
    """Resolve the Xray Tool call from the conversation's draft.

    Raises:
        ValueError: ``conversation_id`` is blank.
    """
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise ValueError("conversation_id must be a non-empty string")
    draft = drafts.find_by_conversation_id(conversation_id.strip())
    if draft is None:
        return XrayDraftUnavailable()
    test_count = exportable_case_count(draft)
    if test_count == 0:
        return XrayDraftUnavailable()
    return PreparedXrayExportCall(
        tool_name=TOOL_NAME,
        arguments=MappingProxyType({"draft_id": draft.draft_id}),  # type: ignore[attr-defined]
        project_key=project_key,
        test_count=test_count,
    )


def exportable_case_count(draft: object) -> int:
    """Count available generated cases whose candidate is still selected."""
    selected = {
        candidate.candidate_id
        for candidate in getattr(draft, "candidates", ())
        if getattr(candidate, "selected", False)
    }
    return sum(
        1
        for case in getattr(draft, "generated_cases", ())
        if case.candidate_id in selected and case.availability == "available"
    )
