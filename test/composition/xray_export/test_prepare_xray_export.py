"""Seam: ``prepare_xray_export_call`` builds the server-side Xray call (#199)."""

from __future__ import annotations

import pytest

from composition.xray_export.prepare import (
    PreparedXrayExportCall,
    XrayDraftUnavailable,
    prepare_xray_export_call,
)
from packs.software_delivery.tools.create_xray_tests import TOOL_NAME
from test.packs.software_delivery.tools.test_create_xray_tests import (
    _candidate,
    _cucumber_case,
    _draft,
    _manual_case,
)


class _Drafts:
    def __init__(self, draft) -> None:
        self.draft = draft
        self.asked: list[str] = []

    def find_by_conversation_id(self, conversation_id: str):
        self.asked.append(conversation_id)
        return self.draft


def test_prepare_binds_the_draft_id_and_counts_exportable_cases() -> None:
    draft = _draft(
        candidates=(
            _candidate("cand-1"),
            _candidate("cand-2", test_type="cucumber"),
            _candidate("cand-3", selected=False),
        ),
        cases=(_manual_case("cand-1"), _cucumber_case("cand-2")),
    )
    drafts = _Drafts(draft)

    prepared = prepare_xray_export_call(
        conversation_id=" conv-1 ", drafts=drafts, project_key="QA"
    )

    assert prepared == PreparedXrayExportCall(
        tool_name=TOOL_NAME,
        arguments={"draft_id": "draft-1"},
        project_key="QA",
        test_count=2,
    )
    assert drafts.asked == ["conv-1"]


def test_prepare_without_a_draft_is_unavailable() -> None:
    prepared = prepare_xray_export_call(
        conversation_id="conv-1", drafts=_Drafts(None), project_key="QA"
    )

    assert isinstance(prepared, XrayDraftUnavailable)


def test_prepare_without_available_selected_cases_is_unavailable() -> None:
    draft = _draft(
        candidates=(_candidate("cand-1"), _candidate("cand-2", selected=False)),
        cases=(
            _manual_case(
                "cand-1",
                availability="insufficient_evidence",
                preconditions="",
                steps=(),
                expected_result="",
            ),
        ),
    )

    prepared = prepare_xray_export_call(
        conversation_id="conv-1", drafts=_Drafts(draft), project_key="QA"
    )

    assert isinstance(prepared, XrayDraftUnavailable)


def test_prepare_arguments_are_immutable() -> None:
    draft = _draft(candidates=(_candidate("cand-1"),), cases=(_manual_case("cand-1"),))
    prepared = prepare_xray_export_call(
        conversation_id="conv-1", drafts=_Drafts(draft), project_key="QA"
    )

    with pytest.raises(TypeError):
        prepared.arguments["draft_id"] = "other"  # type: ignore[index]


@pytest.mark.parametrize("conversation_id", ["", "  "])
def test_prepare_rejects_blank_conversation_id(conversation_id: str) -> None:
    with pytest.raises(ValueError):
        prepare_xray_export_call(
            conversation_id=conversation_id, drafts=_Drafts(None), project_key="QA"
        )
