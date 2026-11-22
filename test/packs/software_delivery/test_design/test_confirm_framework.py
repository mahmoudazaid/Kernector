"""Tests for confirming framework selection on a draft (#368)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from domain.knowledge import SourceReference
from packs.software_delivery.project_profile.models import (
    ComponentProfile,
    ProfileFact,
    TechnologyProfile,
)
from packs.software_delivery.project_profile.service import profile_project
from packs.software_delivery.test_design.confirm_framework import (
    ConfirmFrameworkRequest,
    ConfirmFrameworkSelection,
)
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.models import TestCandidate, TestCoverageDraft


class _MemoryRepo:
    def __init__(self, draft: TestCoverageDraft) -> None:
        self._by_id = {draft.draft_id: draft}

    def create(self, draft: TestCoverageDraft) -> TestCoverageDraft:
        raise NotImplementedError

    def get(self, draft_id: str) -> TestCoverageDraft | None:
        return self._by_id.get(draft_id)

    def update(
        self, draft: TestCoverageDraft, *, expected_version: int
    ) -> TestCoverageDraft:
        current = self._by_id[draft.draft_id]
        if current.version != expected_version:
            raise TestDesignValidationError("version conflict")
        saved = replace(draft, version=expected_version + 1)
        self._by_id[draft.draft_id] = saved
        return saved


def _draft(**overrides: object) -> TestCoverageDraft:
    base: dict[str, object] = {
        "draft_id": "draft-1",
        "workspace_id": "ws-1",
        "conversation_id": "conv-1",
        "source_reference": SourceReference("PROJ-1", "jira"),
        "ticket_identifier": "PROJ-1",
        "source_provider": "jira",
        "status": "ready",
        "candidates": (
            TestCandidate(
                candidate_id="cand-1",
                title="Cancel unpaid order",
                category="positive",
                rationale="AC",
                evidence_references=(SourceReference("PROJ-1", "jira"),),
                selected=True,
                origin="suggested",
            ),
        ),
        "version": 2,
    }
    base.update(overrides)
    return TestCoverageDraft(**base)  # type: ignore[arg-type]


def _profile_oie_tests() -> TechnologyProfile:
    from test.packs.software_delivery.project_profile.conftest import load_component_files

    return profile_project(
        [
            {"component": "oie-tests", "files": load_component_files("acme/oie-tests")},
            {"component": "oie-e2e", "files": load_component_files("acme/oie-e2e")},
        ]
    )


def test_confirm_stores_bounded_selection_for_robot_component() -> None:
    profile = _profile_oie_tests()
    draft = _draft()
    repo = _MemoryRepo(draft)
    result = ConfirmFrameworkSelection(repository=repo).execute(
        ConfirmFrameworkRequest(
            draft_id="draft-1",
            expected_version=2,
            framework_id="robot_framework",
            component_id="oie-tests",
            profile=profile,
            profile_fingerprint=profile.profile_fingerprint,
        )
    )

    assert result.status == "ok"
    assert result.draft is not None
    selection = result.draft.framework_selection
    assert selection is not None
    assert selection.framework_id == "robot_framework"
    assert selection.component_id == "oie-tests"
    assert selection.profile_fingerprint == profile.profile_fingerprint
    assert all(c.framework_id == "robot_framework" for c in selection.reusable_components)
    assert any(c.signature == "Cancel Order" for c in selection.reusable_components)


def test_confirm_rejects_mismatched_fingerprint() -> None:
    profile = _profile_oie_tests()
    repo = _MemoryRepo(_draft())
    with pytest.raises(TestDesignValidationError, match="profile_fingerprint"):
        ConfirmFrameworkSelection(repository=repo).execute(
            ConfirmFrameworkRequest(
                draft_id="draft-1",
                expected_version=2,
                framework_id="robot_framework",
                component_id="oie-tests",
                profile=profile,
                profile_fingerprint="forged",
            )
        )


def test_confirm_rejects_unknown_framework_id() -> None:
    profile = _profile_oie_tests()
    repo = _MemoryRepo(_draft())
    with pytest.raises(TestDesignValidationError, match="framework_id"):
        ConfirmFrameworkSelection(repository=repo).execute(
            ConfirmFrameworkRequest(
                draft_id="draft-1",
                expected_version=2,
                framework_id="karate",
                component_id="oie-tests",
                profile=profile,
                profile_fingerprint=profile.profile_fingerprint,
            )
        )


def test_multi_component_requires_component_id() -> None:
    profile = _profile_oie_tests()
    repo = _MemoryRepo(_draft())
    result = ConfirmFrameworkSelection(repository=repo).execute(
        ConfirmFrameworkRequest(
            draft_id="draft-1",
            expected_version=2,
            framework_id="robot_framework",
            component_id=None,
            profile=profile,
            profile_fingerprint=profile.profile_fingerprint,
        )
    )
    assert result.status == "framework_choice_required"
    assert "oie-tests" in result.component_options
    assert "oie-e2e" in result.component_options
    assert repo.get("draft-1").framework_selection is None


def test_confirm_rejects_client_built_non_profile_object() -> None:
    repo = _MemoryRepo(_draft())
    with pytest.raises(TestDesignValidationError, match="TechnologyProfile"):
        ConfirmFrameworkSelection(repository=repo).execute(
            ConfirmFrameworkRequest(
                draft_id="draft-1",
                expected_version=2,
                framework_id="robot_framework",
                profile={"profile_fingerprint": "x"},  # type: ignore[arg-type]
                profile_fingerprint="x",
            )
        )


def test_confirm_accepts_unlabeled_implicit_component() -> None:
    """Default project_profile evidence has IMPLICIT_COMPONENT label \"\"."""
    from test.packs.software_delivery.project_profile.conftest import load_component_files

    profile = profile_project(
        [{"files": load_component_files("acme/oie-tests")}]
    )
    assert profile.components[0].label == ""
    repo = _MemoryRepo(_draft())
    result = ConfirmFrameworkSelection(repository=repo).execute(
        ConfirmFrameworkRequest(
            draft_id="draft-1",
            expected_version=2,
            framework_id="robot_framework",
            component_id=None,
            profile=profile,
            profile_fingerprint=profile.profile_fingerprint,
        )
    )
    assert result.status == "ok"
    assert result.draft is not None
    selection = result.draft.framework_selection
    assert selection is not None
    assert selection.component_id == ""
    assert selection.framework_id == "robot_framework"


def test_ambiguous_without_framework_id_requires_choice() -> None:
    component = ComponentProfile(
        label="suite",
        facet_status={"test_frameworks": "ambiguous"},
        facts=(
            ProfileFact(
                facet="test_frameworks",
                value="robot_framework",
                confidence="medium",
                evidence_refs=(),
                framework_id="robot_framework",
            ),
            ProfileFact(
                facet="test_frameworks",
                value="pytest",
                confidence="medium",
                evidence_refs=(),
                framework_id="pytest",
            ),
        ),
        conventions=(),
        reusable_components=(),
        diagnostics=(),
    )
    profile = TechnologyProfile(
        profile_fingerprint="fp-amb",
        evidence_origin="client_supplied",
        facet_status={"test_frameworks": "ambiguous"},
        facts=component.facts,
        conventions=(),
        reusable_components=(),
        diagnostics=(),
        components=(component,),
    )
    repo = _MemoryRepo(_draft())
    result = ConfirmFrameworkSelection(repository=repo).execute(
        ConfirmFrameworkRequest(
            draft_id="draft-1",
            expected_version=2,
            framework_id="",
            component_id="suite",
            profile=profile,
            profile_fingerprint="fp-amb",
        )
    )
    assert result.status == "framework_choice_required"
    assert set(result.framework_options) == {"robot_framework", "pytest"}
