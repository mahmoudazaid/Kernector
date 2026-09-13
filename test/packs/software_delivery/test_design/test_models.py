"""Unit tests for Software Delivery test-design draft models."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from domain.knowledge import SourceReference
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.limits import (
    MAX_CANDIDATES,
    MAX_EVIDENCE_REFS,
    MAX_EXPECTED_CHARS,
    MAX_PRECONDITIONS,
    MAX_RATIONALE_CHARS,
    MAX_SCENARIOS,
    MAX_STEPS,
    MAX_STEP_CHARS,
    MAX_TICKET_IDENTIFIER_CHARS,
    MAX_TITLE_CHARS,
)
from packs.software_delivery.test_design.models import (
    COVERAGE_CATEGORIES,
    DRAFT_STATUSES,
    CANDIDATE_ORIGINS,
    CoverageGap,
    TestCandidate,
    TestCoverageDraft,
    TestScenario,
)

BLANK = ["", "   ", "\n"]


def _ref(source_id: str = "PROJ-42", source_type: str = "jira") -> SourceReference:
    return SourceReference(source_id, source_type)


def _candidate(
    *,
    candidate_id: str = "cand-1",
    title: str = "Login succeeds with valid credentials",
    category: str = "happy_path",
    rationale: str = "Happy path login is in acceptance criteria.",
    evidence_references: list[SourceReference] | None = None,
    selected: bool = True,
    origin: str = "suggested",
) -> TestCandidate:
    return TestCandidate(
        candidate_id=candidate_id,
        title=title,
        category=category,
        rationale=rationale,
        evidence_references=evidence_references
        if evidence_references is not None
        else [_ref()],
        selected=selected,
        origin=origin,
    )


def _scenario(
    *,
    scenario_id: str = "scen-1",
    candidate_id: str = "cand-1",
    title: str = "Valid login",
    category: str = "happy_path",
    preconditions: list[str] | None = None,
    steps: list[str] | None = None,
    expected_result: str = "User reaches the dashboard",
    evidence_references: list[SourceReference] | None = None,
) -> TestScenario:
    return TestScenario(
        scenario_id=scenario_id,
        candidate_id=candidate_id,
        title=title,
        category=category,
        preconditions=preconditions if preconditions is not None else ["User exists"],
        steps=steps if steps is not None else ["Open login", "Submit credentials"],
        expected_result=expected_result,
        evidence_references=evidence_references
        if evidence_references is not None
        else [_ref()],
    )


def test_candidate_stores_allowlisted_fields() -> None:
    refs = [_ref("AC-1", "confluence"), _ref("PROJ-42", "jira")]
    candidate = _candidate(evidence_references=refs, origin="manual", selected=False)

    assert candidate.candidate_id == "cand-1"
    assert candidate.title == "Login succeeds with valid credentials"
    assert candidate.category == "happy_path"
    assert candidate.rationale == "Happy path login is in acceptance criteria."
    assert candidate.selected is False
    assert candidate.origin == "manual"
    assert candidate.evidence_references == (
        _ref("AC-1", "confluence"),
        _ref("PROJ-42", "jira"),
    )


def test_candidate_dedupes_and_sorts_evidence_references() -> None:
    refs = [
        _ref("b", "srs"),
        _ref("a", "code"),
        _ref("b", "srs"),
        _ref("a", "confluence"),
    ]
    candidate = _candidate(evidence_references=refs)

    assert candidate.evidence_references == (
        _ref("a", "code"),
        _ref("a", "confluence"),
        _ref("b", "srs"),
    )


def test_candidate_is_immutable() -> None:
    candidate = _candidate()
    with pytest.raises(FrozenInstanceError):
        candidate.title = "other"  # type: ignore[misc]


@pytest.mark.parametrize("blank", BLANK)
def test_candidate_rejects_blank_id(blank: str) -> None:
    with pytest.raises(TestDesignValidationError, match="candidate_id"):
        _candidate(candidate_id=blank)


@pytest.mark.parametrize("blank", BLANK)
def test_candidate_rejects_blank_title(blank: str) -> None:
    with pytest.raises(TestDesignValidationError, match="title"):
        _candidate(title=blank)


def test_candidate_rejects_unknown_category() -> None:
    with pytest.raises(TestDesignValidationError, match="category") as raised:
        _candidate(category="smoke")
    assert "smoke" not in COVERAGE_CATEGORIES
    assert str(sorted(COVERAGE_CATEGORIES)) in str(raised.value)


def test_candidate_rejects_unknown_origin() -> None:
    with pytest.raises(TestDesignValidationError, match="origin"):
        _candidate(origin="imported")


def test_candidate_rejects_title_over_limit() -> None:
    with pytest.raises(TestDesignValidationError, match="title"):
        _candidate(title="x" * (MAX_TITLE_CHARS + 1))


def test_candidate_rejects_rationale_over_limit() -> None:
    with pytest.raises(TestDesignValidationError, match="rationale"):
        _candidate(rationale="x" * (MAX_RATIONALE_CHARS + 1))


def test_candidate_rejects_too_many_evidence_refs() -> None:
    refs = [_ref(f"id-{i}", "jira") for i in range(MAX_EVIDENCE_REFS + 1)]
    with pytest.raises(TestDesignValidationError, match="evidence_references"):
        _candidate(evidence_references=refs)


def test_candidate_rejects_empty_evidence_for_suggested() -> None:
    with pytest.raises(TestDesignValidationError, match="evidence_references"):
        _candidate(origin="suggested", evidence_references=[])


def test_candidate_allows_empty_evidence_for_manual() -> None:
    candidate = _candidate(origin="manual", evidence_references=[])
    assert candidate.evidence_references == ()


def test_coverage_categories_are_the_locked_allowlist() -> None:
    assert COVERAGE_CATEGORIES == frozenset(
        {
            "happy_path",
            "negative",
            "edge_case",
            "integration",
            "permission_security",
            "failure_recovery",
        }
    )


def test_scenario_stores_ordered_steps_and_preconditions() -> None:
    scenario = _scenario(
        preconditions=["Account active", "Session cleared"],
        steps=["Open /login", "Enter password", "Submit"],
    )

    assert scenario.scenario_id == "scen-1"
    assert scenario.candidate_id == "cand-1"
    assert scenario.preconditions == ("Account active", "Session cleared")
    assert scenario.steps == ("Open /login", "Enter password", "Submit")
    assert scenario.expected_result == "User reaches the dashboard"


def test_scenario_dedupes_evidence_references() -> None:
    scenario = _scenario(
        evidence_references=[_ref("b", "srs"), _ref("a", "jira"), _ref("b", "srs")]
    )
    assert scenario.evidence_references == (_ref("a", "jira"), _ref("b", "srs"))


@pytest.mark.parametrize("blank", BLANK)
def test_scenario_rejects_blank_expected_result(blank: str) -> None:
    with pytest.raises(TestDesignValidationError, match="expected_result"):
        _scenario(expected_result=blank)


def test_scenario_rejects_empty_steps() -> None:
    with pytest.raises(TestDesignValidationError, match="steps"):
        _scenario(steps=[])


def test_scenario_rejects_too_many_steps() -> None:
    with pytest.raises(TestDesignValidationError, match="steps"):
        _scenario(steps=[f"step {i}" for i in range(MAX_STEPS + 1)])


def test_scenario_rejects_step_over_limit() -> None:
    with pytest.raises(TestDesignValidationError, match="steps"):
        _scenario(steps=["x" * (MAX_STEP_CHARS + 1)])


def test_scenario_rejects_expected_over_limit() -> None:
    with pytest.raises(TestDesignValidationError, match="expected_result"):
        _scenario(expected_result="x" * (MAX_EXPECTED_CHARS + 1))


def test_scenario_rejects_too_many_preconditions() -> None:
    with pytest.raises(TestDesignValidationError, match="preconditions"):
        _scenario(preconditions=[f"pre {i}" for i in range(MAX_PRECONDITIONS + 1)])


def test_coverage_gap_stores_category_and_detail() -> None:
    gap = CoverageGap(
        category="permission_security",
        detail="No ACL acceptance criteria found for admin roles.",
    )
    assert gap.category == "permission_security"
    assert gap.detail == "No ACL acceptance criteria found for admin roles."


def test_coverage_gap_rejects_unknown_category() -> None:
    with pytest.raises(TestDesignValidationError, match="category"):
        CoverageGap(category="smoke", detail="missing smoke coverage")


def test_draft_constructs_coverage_review_state() -> None:
    candidates = (
        _candidate(candidate_id="cand-1", category="happy_path"),
        _candidate(
            candidate_id="cand-2",
            category="negative",
            title="Login fails with bad password",
            selected=False,
        ),
    )
    gaps = (
        CoverageGap(
            category="permission_security",
            detail="No ACL acceptance criteria found.",
        ),
    )
    draft = TestCoverageDraft(
        draft_id="draft-1",
        workspace_id="ws-1",
        conversation_id="conv-1",
        source_reference=_ref(),
        ticket_identifier="KERN-293",
        status="coverage_review",
        candidates=candidates,
        scenarios=(),
        coverage_gaps=gaps,
        version=1,
    )

    assert draft.draft_id == "draft-1"
    assert draft.workspace_id == "ws-1"
    assert draft.conversation_id == "conv-1"
    assert draft.ticket_identifier == "KERN-293"
    assert draft.status == "coverage_review"
    assert draft.version == 1
    assert draft.selected_candidate_ids == ("cand-1",)
    assert draft.candidates == candidates
    assert draft.coverage_gaps == gaps
    assert draft.scenarios == ()


def test_draft_statuses_are_the_locked_allowlist() -> None:
    assert DRAFT_STATUSES == frozenset(
        {"coverage_review", "scenario_editing", "ready"}
    )


def test_candidate_origins_are_the_locked_allowlist() -> None:
    assert CANDIDATE_ORIGINS == frozenset({"suggested", "manual"})


def test_draft_rejects_duplicate_candidate_ids() -> None:
    with pytest.raises(TestDesignValidationError, match="candidate_id"):
        TestCoverageDraft(
            draft_id="draft-1",
            workspace_id="ws-1",
            conversation_id="conv-1",
            source_reference=_ref(),
            ticket_identifier="KERN-293",
            status="coverage_review",
            candidates=(
                _candidate(candidate_id="cand-1"),
                _candidate(candidate_id="cand-1", title="Other"),
            ),
            scenarios=(),
            coverage_gaps=(),
            version=1,
        )


def test_draft_rejects_duplicate_scenario_ids() -> None:
    with pytest.raises(TestDesignValidationError, match="scenario_id"):
        TestCoverageDraft(
            draft_id="draft-1",
            workspace_id="ws-1",
            conversation_id="conv-1",
            source_reference=_ref(),
            ticket_identifier="KERN-293",
            status="scenario_editing",
            candidates=(_candidate(candidate_id="cand-1"),),
            scenarios=(
                _scenario(scenario_id="scen-1", candidate_id="cand-1"),
                _scenario(scenario_id="scen-1", candidate_id="cand-1", title="Other"),
            ),
            coverage_gaps=(),
            version=2,
        )


def test_draft_rejects_scenario_for_unknown_candidate() -> None:
    with pytest.raises(TestDesignValidationError, match="candidate_id"):
        TestCoverageDraft(
            draft_id="draft-1",
            workspace_id="ws-1",
            conversation_id="conv-1",
            source_reference=_ref(),
            ticket_identifier="KERN-293",
            status="scenario_editing",
            candidates=(_candidate(candidate_id="cand-1"),),
            scenarios=(_scenario(candidate_id="cand-missing"),),
            coverage_gaps=(),
            version=2,
        )


def test_draft_rejects_bare_ticket_identifier() -> None:
    with pytest.raises(TestDesignValidationError, match="ticket_identifier"):
        TestCoverageDraft(
            draft_id="draft-1",
            workspace_id="ws-1",
            conversation_id="conv-1",
            source_reference=_ref(),
            ticket_identifier="293",
            status="coverage_review",
            candidates=(),
            scenarios=(),
            coverage_gaps=(),
            version=1,
        )


@pytest.mark.parametrize("blank", BLANK)
def test_draft_rejects_blank_ticket_identifier(blank: str) -> None:
    with pytest.raises(TestDesignValidationError, match="ticket_identifier"):
        TestCoverageDraft(
            draft_id="draft-1",
            workspace_id="ws-1",
            conversation_id="conv-1",
            source_reference=_ref(),
            ticket_identifier=blank,
            status="coverage_review",
            candidates=(),
            scenarios=(),
            coverage_gaps=(),
            version=1,
        )


def test_draft_rejects_ticket_identifier_over_limit() -> None:
    with pytest.raises(TestDesignValidationError, match="ticket_identifier"):
        TestCoverageDraft(
            draft_id="draft-1",
            workspace_id="ws-1",
            conversation_id="conv-1",
            source_reference=_ref(),
            ticket_identifier="K" * (MAX_TICKET_IDENTIFIER_CHARS + 1),
            status="coverage_review",
            candidates=(),
            scenarios=(),
            coverage_gaps=(),
            version=1,
        )


def test_draft_rejects_unknown_status() -> None:
    with pytest.raises(TestDesignValidationError, match="status"):
        TestCoverageDraft(
            draft_id="draft-1",
            workspace_id="ws-1",
            conversation_id="conv-1",
            source_reference=_ref(),
            ticket_identifier="KERN-293",
            status="published",
            candidates=(),
            scenarios=(),
            coverage_gaps=(),
            version=1,
        )


def test_draft_rejects_non_positive_version() -> None:
    with pytest.raises(TestDesignValidationError, match="version"):
        TestCoverageDraft(
            draft_id="draft-1",
            workspace_id="ws-1",
            conversation_id="conv-1",
            source_reference=_ref(),
            ticket_identifier="KERN-293",
            status="coverage_review",
            candidates=(),
            scenarios=(),
            coverage_gaps=(),
            version=0,
        )


def test_draft_rejects_too_many_candidates() -> None:
    candidates = tuple(
        _candidate(
            candidate_id=f"cand-{i}",
            title=f"Candidate {i}",
            origin="manual",
            evidence_references=[],
        )
        for i in range(MAX_CANDIDATES + 1)
    )
    with pytest.raises(TestDesignValidationError, match="candidates"):
        TestCoverageDraft(
            draft_id="draft-1",
            workspace_id="ws-1",
            conversation_id="conv-1",
            source_reference=_ref(),
            ticket_identifier="KERN-293",
            status="coverage_review",
            candidates=candidates,
            scenarios=(),
            coverage_gaps=(),
            version=1,
        )


def test_draft_rejects_too_many_scenarios() -> None:
    candidates = (
        _candidate(candidate_id="cand-1", origin="manual", evidence_references=[]),
    )
    scenarios = tuple(
        _scenario(scenario_id=f"scen-{i}", candidate_id="cand-1", title=f"Scenario {i}")
        for i in range(MAX_SCENARIOS + 1)
    )
    with pytest.raises(TestDesignValidationError, match="scenarios"):
        TestCoverageDraft(
            draft_id="draft-1",
            workspace_id="ws-1",
            conversation_id="conv-1",
            source_reference=_ref(),
            ticket_identifier="KERN-293",
            status="scenario_editing",
            candidates=candidates,
            scenarios=scenarios,
            coverage_gaps=(),
            version=2,
        )


def test_draft_allows_saved_scenario_for_deselected_candidate() -> None:
    """Deselect keeps stored scenario rows for later reselect."""
    draft = TestCoverageDraft(
        draft_id="draft-1",
        workspace_id="ws-1",
        conversation_id="conv-1",
        source_reference=_ref(),
        ticket_identifier="KERN-293",
        status="scenario_editing",
        candidates=(
            _candidate(candidate_id="cand-1", selected=False),
        ),
        scenarios=(_scenario(candidate_id="cand-1"),),
        coverage_gaps=(),
        version=3,
    )
    assert draft.selected_candidate_ids == ()
    assert draft.scenarios[0].candidate_id == "cand-1"


def test_draft_rejects_invalid_source_reference_type() -> None:
    with pytest.raises(TestDesignValidationError, match="source_reference"):
        TestCoverageDraft(
            draft_id="draft-1",
            workspace_id="ws-1",
            conversation_id="conv-1",
            source_reference="not-a-ref",  # type: ignore[arg-type]
            ticket_identifier="KERN-293",
            status="coverage_review",
            candidates=(),
            scenarios=(),
            coverage_gaps=(),
            version=1,
        )
