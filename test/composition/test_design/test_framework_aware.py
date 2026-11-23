"""Composition tests for framework-aware Test Design (#368)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from composition.test_design.errors import (
    TestDesignNotFoundError,
    TestDesignValidationError,
    TestDesignVersionConflictError,
)
from composition.test_design.facade import (
    FrameworkConfirmView,
    FrameworkGenerateView,
    TestDesignFacade,
)
from domain.knowledge import SourceReference
from packs.software_delivery.project_profile.service import profile_project
from packs.software_delivery.test_design.models import (
    GeneratedTestCase,
    TestCandidate,
    TestCoverageDraft,
)
from test.composition.test_design.test_design_fakes import settings_with_pack
from test.packs.software_delivery.project_profile.conftest import load_component_files


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


def _facade(repo: _MemoryRepo) -> TestDesignFacade:
    from pathlib import Path

    from composition.test_design.sources import TestDesignSourceRegistry

    facade = TestDesignFacade(
        settings=settings_with_pack(workspace_id="ws-1"),
        store_path=Path("/tmp/unused-test-design-store"),
        workspace_id="ws-1",
        sources=TestDesignSourceRegistry(()),
    )

    def _repo():
        return repo

    facade._repository = _repo  # type: ignore[method-assign]
    return facade


def _draft() -> TestCoverageDraft:
    return TestCoverageDraft(
        draft_id="draft-1",
        workspace_id="ws-1",
        conversation_id="conv-1",
        source_reference=SourceReference("PROJ-1", "jira"),
        ticket_identifier="PROJ-1",
        source_provider="jira",
        status="case_editing",
        candidates=(
            TestCandidate(
                candidate_id="cand-1",
                title="Cancel Unpaid Order",
                category="positive",
                rationale="AC",
                evidence_references=(SourceReference("PROJ-1", "jira"),),
                selected=True,
                origin="suggested",
                test_type="cucumber",
            ),
        ),
        version=2,
        generated_cases=(
            GeneratedTestCase(
                candidate_id="cand-1",
                test_type="cucumber",
                automation_fit="applicable",
                automation_rationale="",
                availability="available",
                preconditions="",
                steps=(),
                expected_result="",
                gherkin=(
                    "Scenario: Cancel unpaid order\n"
                    "  Given Create Unpaid Order\n"
                    "  When Cancel Order\n"
                ),
                user_edited=False,
            ),
        ),
    )


def _evidence() -> list[dict[str, object]]:
    return [
        {"component": "oie-tests", "files": load_component_files("acme/oie-tests")},
    ]


def test_confirm_stale_version_is_version_conflict_not_validation() -> None:
    facade = _facade(_MemoryRepo(_draft()))
    profile = profile_project(_evidence())
    with pytest.raises(TestDesignVersionConflictError):
        facade.confirm_framework_profile(
            "draft-1",
            expected_version=1,
            framework_id="robot_framework",
            profile_fingerprint=profile.profile_fingerprint,
            evidence=_evidence(),
            component_id="oie-tests",
        )


def test_confirm_unknown_draft_is_not_found_not_validation() -> None:
    facade = _facade(_MemoryRepo(_draft()))
    profile = profile_project(_evidence())
    with pytest.raises(TestDesignNotFoundError):
        facade.confirm_framework_profile(
            "missing",
            expected_version=2,
            framework_id="robot_framework",
            profile_fingerprint=profile.profile_fingerprint,
            evidence=_evidence(),
            component_id="oie-tests",
        )


def test_generate_stale_version_is_version_conflict_not_validation() -> None:
    evidence = _evidence()
    profile = profile_project(evidence)
    repo = _MemoryRepo(_draft())
    facade = _facade(repo)
    confirmed = facade.confirm_framework_profile(
        "draft-1",
        expected_version=2,
        framework_id="robot_framework",
        profile_fingerprint=profile.profile_fingerprint,
        evidence=evidence,
        component_id="oie-tests",
    )
    assert confirmed.draft is not None
    with pytest.raises(TestDesignVersionConflictError):
        facade.generate_framework_tests("draft-1", expected_version=1)


def test_generate_unknown_draft_is_not_found_not_validation() -> None:
    facade = _facade(_MemoryRepo(_draft()))
    with pytest.raises(TestDesignNotFoundError):
        facade.generate_framework_tests("nope", expected_version=2)


def test_confirm_unlabeled_evidence_succeeds_without_component_id() -> None:
    evidence = [{"files": load_component_files("acme/oie-tests")}]
    profile = profile_project(evidence)
    facade = _facade(_MemoryRepo(_draft()))
    confirmed = facade.confirm_framework_profile(
        "draft-1",
        expected_version=2,
        framework_id="robot_framework",
        profile_fingerprint=profile.profile_fingerprint,
        evidence=evidence,
        component_id=None,
    )
    assert confirmed.status == "ok"
    assert confirmed.framework_selection is not None
    assert confirmed.framework_selection.component_id == "__implicit__"


def test_composition_confirm_recomputes_profile_and_rejects_forged_fingerprint() -> None:
    facade = _facade(_MemoryRepo(_draft()))
    with pytest.raises(TestDesignValidationError):
        facade.confirm_framework_profile(
            "draft-1",
            expected_version=2,
            framework_id="robot_framework",
            profile_fingerprint="forged",
            evidence=_evidence(),
            component_id="oie-tests",
        )


def test_composition_profile_confirm_then_generate_robot() -> None:
    evidence = _evidence()
    profile = profile_project(evidence)
    repo = _MemoryRepo(_draft())
    facade = _facade(repo)

    confirmed = facade.confirm_framework_profile(
        "draft-1",
        expected_version=2,
        framework_id="robot_framework",
        profile_fingerprint=profile.profile_fingerprint,
        evidence=evidence,
        component_id="oie-tests",
    )
    assert isinstance(confirmed, FrameworkConfirmView)
    assert confirmed.status == "ok"
    assert confirmed.framework_selection is not None
    assert confirmed.framework_selection.framework_id == "robot_framework"
    assert confirmed.draft is not None

    generated = facade.generate_framework_tests(
        "draft-1", expected_version=confirmed.draft.version
    )
    assert isinstance(generated, FrameworkGenerateView)
    assert generated.status == "ok"
    assert generated.files
    assert generated.files[0].suggested_path.endswith(".robot")
    assert "Create Unpaid Order" in generated.files[0].content
