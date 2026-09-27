"""Unit tests for Software Delivery test-design draft models."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from domain.knowledge import SourceReference
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.limits import (
    MAX_CANDIDATES,
    MAX_EXPECTED_RESULT_LINES,
    MAX_ID_CHARS,
    MAX_PRECONDITIONS_LINES,
    MAX_RATIONALE_CHARS,
    MAX_TITLE_CHARS,
)
from packs.software_delivery.test_design.models import (
    COVERAGE_CATEGORIES,
    DRAFT_STATUSES,
    GeneratedTestCase,
    TestCandidate,
    TestCoverageDraft,
    coverage_candidate_fingerprint,
    drop_generated_cases_for_type_changes,
    is_deselection_only,
    is_title_only_change,
    keep_generated_cases_for_unchanged_candidates,
)


def _ref(source_id: str = "PROJ-42") -> SourceReference:
    return SourceReference(source_id, "jira")


def _candidate(**overrides: object) -> TestCandidate:
    base: dict[str, object] = {
        "candidate_id": "cand-1",
        "title": "Valid login",
        "category": "positive",
        "rationale": "AC covers login.",
        "evidence_references": (_ref(),),
        "selected": True,
        "origin": "suggested",
    }
    base.update(overrides)
    return TestCandidate(**base)  # type: ignore[arg-type]


def _draft(**overrides: object) -> TestCoverageDraft:
    base: dict[str, object] = {
        "draft_id": "draft-1",
        "workspace_id": "ws-1",
        "conversation_id": "conv-1",
        "source_reference": _ref(),
        "ticket_identifier": "KERN-293",
        "status": "coverage_review",
        "candidates": (_candidate(),),
        "version": 1,
    }
    base.update(overrides)
    return TestCoverageDraft(**base)  # type: ignore[arg-type]


def test_candidate_rejects_blank_title() -> None:
    with pytest.raises(TestDesignValidationError, match="title"):
        _candidate(title=" ")


def test_candidate_rejects_oversized_title() -> None:
    with pytest.raises(TestDesignValidationError, match="title"):
        _candidate(title="x" * (MAX_TITLE_CHARS + 1))


def test_candidate_rejects_oversized_rationale() -> None:
    with pytest.raises(TestDesignValidationError, match="rationale"):
        _candidate(rationale="x" * (MAX_RATIONALE_CHARS + 1))


def test_candidate_rejects_unknown_category() -> None:
    with pytest.raises(TestDesignValidationError) as raised:
        _candidate(category="smoke")
    assert "smoke" not in COVERAGE_CATEGORIES
    assert str(sorted(COVERAGE_CATEGORIES)) in str(raised.value)


def test_candidate_allows_empty_evidence_for_manual() -> None:
    candidate = _candidate(origin="manual", evidence_references=())
    assert candidate.evidence_references == ()


def test_candidate_requires_evidence_for_suggested() -> None:
    with pytest.raises(TestDesignValidationError, match="evidence_references"):
        _candidate(origin="suggested", evidence_references=())



def test_draft_selected_candidate_ids() -> None:
    draft = _draft(
        candidates=(
            _candidate(candidate_id="cand-1", selected=True),
            _candidate(candidate_id="cand-2", selected=False),
        )
    )
    assert draft.selected_candidate_ids == ("cand-1",)


def test_draft_statuses_include_case_editing() -> None:
    assert DRAFT_STATUSES == frozenset(
        {"coverage_review", "ready", "case_editing"}
    )


def test_candidate_accepts_manual_and_cucumber_test_type() -> None:
    assert _candidate(test_type="manual").test_type == "manual"
    assert _candidate(test_type="cucumber").test_type == "cucumber"
    assert _candidate(test_type=None).test_type is None


def test_candidate_rejects_unknown_test_type() -> None:
    with pytest.raises(TestDesignValidationError, match="test_type"):
        _candidate(test_type="gherkin")


def test_generated_manual_case_requires_content_fields() -> None:
    case = GeneratedTestCase(
        candidate_id="cand-1",
        test_type="manual",
        automation_fit="applicable",
        automation_rationale="Stable UI path.",
        availability="available",
        preconditions="User is logged out.",
        steps=("Enter valid credentials", "Submit"),
        expected_result="User lands on home.",
        gherkin="",
        user_edited=False,
    )
    assert case.steps == ("Enter valid credentials", "Submit")
    assert case.expected_result == "User lands on home."


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("preconditions", MAX_PRECONDITIONS_LINES),
        ("expected_result", MAX_EXPECTED_RESULT_LINES),
    ],
)
def test_generated_manual_case_caps_line_counts(field: str, limit: int) -> None:
    fields: dict[str, object] = {
        "candidate_id": "cand-1",
        "test_type": "manual",
        "automation_fit": "applicable",
        "automation_rationale": "Stable UI path.",
        "availability": "available",
        "preconditions": "User is logged out.",
        "steps": ("Submit",),
        "expected_result": "User lands on home.",
        "gherkin": "",
        "user_edited": False,
    }
    GeneratedTestCase(**(fields | {field: "\n".join(["line"] * limit)}))  # type: ignore[arg-type]
    with pytest.raises(TestDesignValidationError, match=f"{field}.*lines"):
        GeneratedTestCase(**(fields | {field: "\n".join(["line"] * (limit + 1))}))  # type: ignore[arg-type]


def test_generated_manual_case_rejects_gherkin_when_available() -> None:
    with pytest.raises(TestDesignValidationError, match="gherkin"):
        GeneratedTestCase(
            candidate_id="cand-1",
            test_type="manual",
            automation_fit="applicable",
            automation_rationale="Stable UI path.",
            availability="available",
            preconditions="User is logged out.",
            steps=("Enter valid credentials",),
            expected_result="User lands on home.",
            gherkin="Feature: Login",
            user_edited=False,
        )


def test_generated_cucumber_case_requires_gherkin() -> None:
    case = GeneratedTestCase(
        candidate_id="cand-1",
        test_type="cucumber",
        automation_fit="not_applicable",
        automation_rationale="Exploratory.",
        availability="available",
        preconditions="",
        steps=(),
        expected_result="",
        gherkin="Feature: Login\n  Scenario: Valid\n    Given logged out",
        user_edited=False,
    )
    assert "Feature: Login" in case.gherkin


def test_generated_cucumber_case_rejects_manual_fields_when_available() -> None:
    with pytest.raises(TestDesignValidationError, match="preconditions"):
        GeneratedTestCase(
            candidate_id="cand-1",
            test_type="cucumber",
            automation_fit="unclear",
            automation_rationale="Ambiguous AC.",
            availability="available",
            preconditions="User is logged out.",
            steps=(),
            expected_result="",
            gherkin="Feature: Login",
            user_edited=False,
        )


def test_insufficient_evidence_case_rejects_invented_content() -> None:
    with pytest.raises(TestDesignValidationError, match="insufficient_evidence"):
        GeneratedTestCase(
            candidate_id="cand-1",
            test_type="manual",
            automation_fit="unclear",
            automation_rationale="Body lacks steps.",
            availability="insufficient_evidence",
            preconditions="Invented setup.",
            steps=("Invented step",),
            expected_result="Invented result.",
            gherkin="",
            user_edited=False,
        )


def test_insufficient_evidence_case_allows_empty_content() -> None:
    case = GeneratedTestCase(
        candidate_id="cand-1",
        test_type="manual",
        automation_fit="unclear",
        automation_rationale="Body lacks steps.",
        availability="insufficient_evidence",
        preconditions="",
        steps=(),
        expected_result="",
        gherkin="",
        user_edited=False,
    )
    assert case.availability == "insufficient_evidence"


def test_draft_accepts_generated_cases_and_fingerprint() -> None:
    case = GeneratedTestCase(
        candidate_id="cand-1",
        test_type="manual",
        automation_fit="applicable",
        automation_rationale="Stable.",
        availability="available",
        preconditions="Logged out.",
        steps=("Login",),
        expected_result="Home.",
        gherkin="",
        user_edited=False,
    )
    draft = _draft(
        status="case_editing",
        generated_cases=(case,),
        evidence_fingerprint="abc123",
    )
    assert draft.generated_cases == (case,)
    assert draft.evidence_fingerprint == "abc123"


def test_draft_rejects_duplicate_generated_candidate_ids() -> None:
    case = GeneratedTestCase(
        candidate_id="cand-1",
        test_type="manual",
        automation_fit="applicable",
        automation_rationale="Stable.",
        availability="available",
        preconditions="Logged out.",
        steps=("Login",),
        expected_result="Home.",
        gherkin="",
        user_edited=False,
    )
    with pytest.raises(TestDesignValidationError, match="unique candidate_id"):
        _draft(generated_cases=(case, case))


def test_draft_rejects_generated_case_for_unselected_candidate() -> None:
    case = GeneratedTestCase(
        candidate_id="cand-2",
        test_type="manual",
        automation_fit="applicable",
        automation_rationale="Stable.",
        availability="available",
        preconditions="Logged out.",
        steps=("Login",),
        expected_result="Home.",
        gherkin="",
        user_edited=False,
    )
    with pytest.raises(TestDesignValidationError, match="selected"):
        _draft(
            candidates=(
                _candidate(candidate_id="cand-1", selected=True),
                _candidate(candidate_id="cand-2", selected=False),
            ),
            generated_cases=(case,),
        )


def test_coverage_fingerprint_excludes_test_type() -> None:
    left = _candidate(test_type=None)
    right = _candidate(test_type="cucumber")
    assert coverage_candidate_fingerprint(left) == coverage_candidate_fingerprint(
        right
    )


def test_drop_generated_cases_for_type_changes() -> None:
    cases = (
        GeneratedTestCase(
            candidate_id="cand-1",
            test_type="manual",
            automation_fit="applicable",
            automation_rationale="Stable.",
            availability="available",
            preconditions="Logged out.",
            steps=("Login",),
            expected_result="Home.",
            gherkin="",
            user_edited=False,
        ),
        GeneratedTestCase(
            candidate_id="cand-2",
            test_type="cucumber",
            automation_fit="unclear",
            automation_rationale="Ambiguous.",
            availability="available",
            preconditions="",
            steps=(),
            expected_result="",
            gherkin="Feature: X",
            user_edited=True,
        ),
    )
    previous = (
        _candidate(candidate_id="cand-1", test_type="manual"),
        _candidate(candidate_id="cand-2", test_type="cucumber"),
    )
    updated = (
        _candidate(candidate_id="cand-1", test_type="cucumber"),
        _candidate(candidate_id="cand-2", test_type="cucumber"),
    )
    kept = drop_generated_cases_for_type_changes(
        cases, previous=previous, updated=updated
    )
    assert [case.candidate_id for case in kept] == ["cand-2"]


def test_draft_rejects_bare_ticket_number() -> None:
    with pytest.raises(TestDesignValidationError, match="ticket_identifier"):
        _draft(ticket_identifier="293")


def test_draft_rejects_duplicate_candidate_ids() -> None:
    with pytest.raises(TestDesignValidationError, match="unique candidate_id"):
        _draft(
            candidates=(
                _candidate(candidate_id="cand-1"),
                _candidate(candidate_id="cand-1", title="Other"),
            )
        )


def test_draft_rejects_too_many_candidates() -> None:
    candidates = tuple(
        _candidate(candidate_id=f"cand-{i}", title=f"C{i}")
        for i in range(MAX_CANDIDATES + 1)
    )
    with pytest.raises(TestDesignValidationError, match="candidates"):
        _draft(candidates=candidates)


def test_draft_rejects_oversized_ids() -> None:
    with pytest.raises(TestDesignValidationError, match="draft_id"):
        _draft(draft_id="x" * (MAX_ID_CHARS + 1))


def test_coverage_categories_are_locked() -> None:
    assert COVERAGE_CATEGORIES == frozenset(
        {"positive", "negative", "edge_case"}
    )


def test_cucumber_gherkin_and_background_keep_step_lines_only() -> None:
    case = GeneratedTestCase(
        candidate_id="cand-1",
        test_type="cucumber",
        automation_fit="applicable",
        automation_rationale="Stable.",
        availability="available",
        preconditions="",
        steps=(),
        expected_result="",
        gherkin="  Scenario: Valid\n    Given logged out\n\n    And on login\n  Then home",
        user_edited=False,
    )
    assert case.gherkin == "Given logged out\nAnd on login\nThen home"

    draft = _draft(cucumber_background="Background:\n  Given the app is open\n")
    assert draft.cucumber_background == "Given the app is open"


def test_keep_generated_cases_for_unchanged_candidates() -> None:
    cases = tuple(
        GeneratedTestCase(
            candidate_id=candidate_id,
            test_type="manual",
            automation_fit="applicable",
            automation_rationale="Stable.",
            availability="available",
            preconditions="Logged out.",
            steps=("Login",),
            expected_result="Home.",
            gherkin="",
            user_edited=False,
        )
        for candidate_id in ("cand-1", "cand-2", "cand-3", "cand-4")
    )
    previous = (
        _candidate(candidate_id="cand-1", test_type="manual"),
        _candidate(candidate_id="cand-2", title="Two", test_type="manual"),
        _candidate(candidate_id="cand-3", title="Three", test_type="manual"),
        _candidate(candidate_id="cand-4", title="Four", test_type="manual"),
    )
    updated = (
        _candidate(candidate_id="cand-1", test_type="manual"),
        _candidate(candidate_id="cand-2", title="Two edited", test_type="manual"),
        _candidate(candidate_id="cand-3", title="Three", test_type="cucumber"),
        _candidate(candidate_id="cand-4", title="Four", selected=False, test_type="manual"),
        _candidate(candidate_id="cand-5", title="New", test_type="manual"),
    )

    kept = keep_generated_cases_for_unchanged_candidates(
        cases, previous=previous, updated=updated
    )

    assert [case.candidate_id for case in kept] == ["cand-1"]


def test_is_deselection_only_detects_pure_unselect() -> None:
    before = (_candidate(), _candidate(candidate_id="cand-2", title="Other"))
    after = (
        _candidate(),
        _candidate(candidate_id="cand-2", title="Other", selected=False),
    )
    assert is_deselection_only(before, after) is True


def test_is_deselection_only_rejects_other_changes() -> None:
    before = (_candidate(), _candidate(candidate_id="cand-2", title="Other"))
    assert is_deselection_only(before, before) is False
    assert (
        is_deselection_only(
            before,
            (
                _candidate(title="Renamed"),
                _candidate(candidate_id="cand-2", title="Other", selected=False),
            ),
        )
        is False
    )
    assert is_deselection_only(before, (_candidate(),)) is False
    assert (
        is_deselection_only(
            (_candidate(selected=False),),
            (_candidate(),),
        )
        is False
    )


def test_is_title_only_change_detects_pure_rename() -> None:
    before = (_candidate(), _candidate(candidate_id="cand-2", title="Other"))
    after = (_candidate(title="Renamed"), before[1])
    assert is_title_only_change(before, after) is True


def test_is_title_only_change_rejects_other_changes() -> None:
    before = (_candidate(), _candidate(candidate_id="cand-2", title="Other"))
    assert is_title_only_change(before, before) is False
    assert (
        is_title_only_change(
            before,
            (_candidate(title="Renamed"), _candidate(candidate_id="cand-2", selected=False)),
        )
        is False
    )
    assert (
        is_title_only_change(
            (_candidate(test_type="manual"),),
            (_candidate(title="Renamed", test_type="cucumber"),),
        )
        is False
    )
    assert is_title_only_change(before, (_candidate(title="Renamed"),)) is False


def test_models_are_frozen() -> None:
    candidate = _candidate()
    with pytest.raises(FrozenInstanceError):
        candidate.title = "mutated"  # type: ignore[misc]
