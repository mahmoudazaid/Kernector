"""Tests for Google Drive export prepared-call seam (#309)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pytest

from composition.prepare_drive_export import (
    DraftUnavailable,
    PreparedDriveExportCall,
    prepare_drive_export_call,
)
from domain.knowledge import SourceReference
from packs.software_delivery.test_design.models import (
    TestCandidate,
    TestCoverageDraft,
)
from packs.software_delivery.tools.export_test_cases_google_drive import TOOL_NAME


@dataclass(frozen=True, slots=True)
class _Dest:
    folder_id: str
    display_label: str


def _ref() -> SourceReference:
    return SourceReference("AUTH-101", "user_story")


def _draft(
    *,
    conversation_id: str = "conv-1",
    selected: tuple[bool, ...] = (True, True, False),
) -> TestCoverageDraft:
    titles = ("Login MFA", "Idle timeout", "Revoke token")
    candidates = tuple(
        TestCandidate(
            candidate_id=f"cand-{index}",
            title=title,
            category="positive",
            rationale="from AC",
            evidence_references=(_ref(),),
            selected=is_selected,
            origin="suggested",
        )
        for index, (title, is_selected) in enumerate(zip(titles, selected), start=1)
    )
    return TestCoverageDraft(
        draft_id="draft-1",
        workspace_id="ws-a",
        conversation_id=conversation_id,
        source_reference=_ref(),
        ticket_identifier="KERN-482",
        status="ready",
        candidates=candidates,
        version=1,
    )


class _FakeDrafts:
    def __init__(self, draft: TestCoverageDraft | None) -> None:
        self._draft = draft

    def find_by_conversation_id(self, conversation_id: str) -> TestCoverageDraft | None:
        if self._draft is None:
            return None
        if self._draft.conversation_id != conversation_id:
            return None
        return self._draft


class _FakeDestinations:
    def __init__(self, dest: _Dest | None) -> None:
        self._dest = dest

    def get(self, conversation_id: str) -> _Dest | None:
        del conversation_id
        return self._dest


def test_prepare_defaults_to_home_when_no_destination() -> None:
    result = prepare_drive_export_call(
        conversation_id="conv-1",
        drafts=_FakeDrafts(_draft()),
        destinations=_FakeDestinations(None),
    )
    assert isinstance(result, PreparedDriveExportCall)
    assert result.destination_label == "Home"
    assert result.arguments["folder_id"] == "root"
    assert result.selected_title_count == 2
    assert result.arguments["titles"] == ["Login MFA", "Idle timeout"]
    assert result.file_name == "KERN-482.md"
    assert result.arguments["file_name"] == "KERN-482.md"


def test_prepare_returns_draft_unavailable_when_no_draft() -> None:
    result = prepare_drive_export_call(
        conversation_id="conv-1",
        drafts=_FakeDrafts(None),
        destinations=_FakeDestinations(_Dest("folder-abc", "QA exports")),
    )
    assert isinstance(result, DraftUnavailable)


def test_prepare_returns_draft_unavailable_when_no_selected_titles() -> None:
    result = prepare_drive_export_call(
        conversation_id="conv-1",
        drafts=_FakeDrafts(_draft(selected=(False, False, False))),
        destinations=_FakeDestinations(_Dest("folder-abc", "QA exports")),
    )
    assert isinstance(result, DraftUnavailable)


def test_prepare_builds_drive_tool_arguments_from_draft_and_destination() -> None:
    result = prepare_drive_export_call(
        conversation_id="conv-1",
        drafts=_FakeDrafts(_draft()),
        destinations=_FakeDestinations(_Dest("folder-abc", "QA / Sprint 3")),
    )
    assert isinstance(result, PreparedDriveExportCall)
    assert result.tool_name == TOOL_NAME
    assert result.destination_label == "QA / Sprint 3"
    assert result.selected_title_count == 2
    assert result.arguments == {
        "document_title": "KERN-482",
        "titles": ["Login MFA", "Idle timeout"],
        "folder_id": "folder-abc",
        "file_name": "KERN-482.md",
    }
    assert result.file_name == "KERN-482.md"


def test_prepare_rejects_blank_conversation_id() -> None:
    with pytest.raises(ValueError, match="conversation_id"):
        prepare_drive_export_call(
            conversation_id="  ",
            drafts=_FakeDrafts(_draft()),
            destinations=_FakeDestinations(_Dest("folder-abc", "QA")),
        )


def test_prepared_call_arguments_are_immutable_mapping() -> None:
    result = prepare_drive_export_call(
        conversation_id="conv-1",
        drafts=_FakeDrafts(_draft()),
        destinations=_FakeDestinations(_Dest("folder-abc", "QA")),
    )
    assert isinstance(result, PreparedDriveExportCall)
    assert isinstance(result.arguments, Mapping)
    with pytest.raises(TypeError):
        result.arguments["folder_id"] = "mutated"  # type: ignore[index]
