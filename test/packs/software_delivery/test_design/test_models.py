"""Unit tests for Software Delivery test-design draft models."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from domain.knowledge import SourceReference
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.limits import (
    MAX_CANDIDATES,
    MAX_ID_CHARS,
    MAX_RATIONALE_CHARS,
    MAX_TITLE_CHARS,
)
from packs.software_delivery.test_design.models import (
    COVERAGE_CATEGORIES,
    DRAFT_STATUSES,
    TestCandidate,
    TestCoverageDraft,
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


def test_draft_statuses_exclude_scenario_editing() -> None:
    assert DRAFT_STATUSES == frozenset({"coverage_review", "ready"})


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


def test_models_are_frozen() -> None:
    candidate = _candidate()
    with pytest.raises(FrozenInstanceError):
        candidate.title = "mutated"  # type: ignore[misc]
