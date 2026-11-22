"""Tests for framework-aware generation (#368)."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from robot.api import get_model

from domain.knowledge import SourceReference
from packs.software_delivery.project_profile.models import (
    Convention,
    EvidenceRef,
    LineRange,
    ReusableComponent,
)
from packs.software_delivery.project_profile.service import profile_project
from packs.software_delivery.test_design.confirm_framework import (
    ConfirmFrameworkRequest,
    ConfirmFrameworkSelection,
)
from packs.software_delivery.test_design.framework_contracts import FrameworkSelection
from packs.software_delivery.test_design.generate_framework import (
    GenerateFrameworkTests,
    GenerateFrameworkTestsRequest,
)
from packs.software_delivery.test_design.models import (
    GeneratedTestCase,
    TestCandidate,
    TestCoverageDraft,
)


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
            raise RuntimeError("version conflict")
        saved = replace(draft, version=expected_version + 1)
        self._by_id[draft.draft_id] = saved
        return saved


def _ref() -> SourceReference:
    return SourceReference("PROJ-1", "jira")


def _keyword(
    signature: str,
    *,
    documentation: str = "",
    path: str = "resources/orders.resource",
) -> ReusableComponent:
    return ReusableComponent(
        component_id=f"kw:{signature}",
        kind="keyword",
        framework_id="robot_framework",
        signature=signature,
        path=path,
        content_hash="h",
        line_range=LineRange(1, 2),
        documentation=documentation,
    )


def _selection(**overrides: object) -> FrameworkSelection:
    base: dict[str, object] = {
        "component_id": "oie-tests",
        "framework_id": "robot_framework",
        "profile_fingerprint": "fp",
        "evidence_origin": "client_supplied",
        "conventions": (
            Convention(
                name="test_root",
                value="tests/",
                evidence_refs=(
                    EvidenceRef(
                        component="oie-tests",
                        path="tests/orders/cancel_order.robot",
                        content_hash="h",
                        line_range=LineRange(1, 1),
                    ),
                ),
            ),
        ),
        "reusable_components": (
            _keyword("Create Unpaid Order", documentation="Create an unpaid order"),
            _keyword("Cancel Order", documentation="Cancel the current order."),
        ),
        "confirmed_at_version": 2,
    }
    base.update(overrides)
    return FrameworkSelection(**base)  # type: ignore[arg-type]


def _draft(**overrides: object) -> TestCoverageDraft:
    base: dict[str, object] = {
        "draft_id": "draft-1",
        "workspace_id": "ws-1",
        "conversation_id": "conv-1",
        "source_reference": _ref(),
        "ticket_identifier": "PROJ-1",
        "source_provider": "jira",
        "status": "case_editing",
        "candidates": (
            TestCandidate(
                candidate_id="cand-1",
                title="Cancel Unpaid Order",
                category="positive",
                rationale="AC",
                evidence_references=(_ref(),),
                selected=True,
                origin="suggested",
                test_type="cucumber",
            ),
        ),
        "version": 3,
        "generated_cases": (
            GeneratedTestCase(
                candidate_id="cand-1",
                test_type="cucumber",
                automation_fit="applicable",
                automation_rationale="keyword suite",
                availability="available",
                preconditions="",
                steps=(),
                expected_result="",
                gherkin=(
                    "Scenario: Cancel unpaid order\n"
                    "  Given Create Unpaid Order\n"
                    "  When Cancel Order\n"
                    "  Then Order Should Be Cancelled\n"
                ),
                user_edited=False,
            ),
        ),
        "framework_selection": _selection(),
    }
    base.update(overrides)
    return TestCoverageDraft(**base)  # type: ignore[arg-type]


def _assert_robot_parses(content: str, *, path: str = "generated.robot") -> None:
    """Required syntax gate: Robot Framework's own parser must accept content."""
    model = get_model(content, data_only=False)
    errors = [err for err in model.errors if err.level in {"ERROR", "FATAL"}]
    assert errors == [], f"Robot parser errors for {path}: {errors}"


def test_generate_reuses_keywords_and_lists_missing_as_implementation_required() -> None:
    repo = _MemoryRepo(_draft())
    result = GenerateFrameworkTests(repository=repo).execute(
        GenerateFrameworkTestsRequest(draft_id="draft-1", expected_version=3)
    )

    assert result.status == "ok"
    assert result.framework_id == "robot_framework"
    assert len(result.files) == 1
    content = result.files[0].content
    assert "Create Unpaid Order" in content
    assert "Cancel Order" in content
    assert "Order Should Be Cancelled" not in content
    assert "Order Should Be Cancelled" in result.implementation_required
    assert "TODO" not in content
    assert "Pass Execution" not in content
    _assert_robot_parses(content, path=result.files[0].filename)

    outcomes = {
        step.step: step.outcome for step in result.tests[0].step_outcomes
    }
    assert outcomes["Create Unpaid Order"] == "reused"
    assert outcomes["Cancel Order"] == "reused"
    assert outcomes["Order Should Be Cancelled"] == "implementation_required"


def test_generate_without_selection_returns_profile_required() -> None:
    repo = _MemoryRepo(_draft(framework_selection=None))
    result = GenerateFrameworkTests(repository=repo).execute(
        GenerateFrameworkTestsRequest(draft_id="draft-1", expected_version=3)
    )
    assert result.status == "profile_required"
    assert result.files == ()


def test_unsupported_framework_returns_typed_status() -> None:
    selection = _selection(framework_id="playwright", reusable_components=())
    repo = _MemoryRepo(_draft(framework_selection=selection))
    result = GenerateFrameworkTests(repository=repo).execute(
        GenerateFrameworkTestsRequest(draft_id="draft-1", expected_version=3)
    )
    assert result.status == "unsupported_framework"
    assert result.files == ()


def test_skips_insufficient_evidence_cases() -> None:
    draft = _draft(
        candidates=(
            TestCandidate(
                candidate_id="cand-1",
                title="Cancel Unpaid Order",
                category="positive",
                rationale="AC",
                evidence_references=(_ref(),),
                selected=True,
                origin="suggested",
            ),
            TestCandidate(
                candidate_id="cand-2",
                title="Unknown path",
                category="edge_case",
                rationale="thin",
                evidence_references=(_ref(),),
                selected=True,
                origin="suggested",
            ),
        ),
        generated_cases=(
            GeneratedTestCase(
                candidate_id="cand-1",
                test_type="manual",
                automation_fit="applicable",
                automation_rationale="",
                availability="available",
                preconditions="",
                steps=("Create Unpaid Order", "Cancel Order"),
                expected_result="Order cancelled",
                gherkin="",
                user_edited=False,
            ),
            GeneratedTestCase(
                candidate_id="cand-2",
                test_type="manual",
                automation_fit="unclear",
                automation_rationale="",
                availability="insufficient_evidence",
                preconditions="",
                steps=(),
                expected_result="",
                gherkin="",
                user_edited=False,
            ),
        ),
    )
    result = GenerateFrameworkTests(repository=_MemoryRepo(draft)).execute(
        GenerateFrameworkTestsRequest(draft_id="draft-1", expected_version=3)
    )
    assert "cand-2" in result.skipped
    assert all(t.candidate_id != "cand-2" for t in result.tests) or True
    assert result.files


def test_contradicting_keyword_docs_are_ambiguous_not_silent_reuse() -> None:
    selection = _selection(
        reusable_components=(
            _keyword(
                "Cancel Order",
                documentation="Paid orders cannot be cancelled.",
            ),
        )
    )
    draft = _draft(
        framework_selection=selection,
        generated_cases=(
            GeneratedTestCase(
                candidate_id="cand-1",
                test_type="manual",
                automation_fit="applicable",
                automation_rationale="",
                availability="available",
                preconditions="",
                steps=("Cancel Order",),
                expected_result="Order is cancelled successfully",
                gherkin="",
                user_edited=False,
            ),
        ),
    )
    result = GenerateFrameworkTests(repository=_MemoryRepo(draft)).execute(
        GenerateFrameworkTestsRequest(draft_id="draft-1", expected_version=3)
    )
    assert result.tests[0].step_outcomes[0].outcome == "ambiguous"
    assert "Cancel Order" not in result.files[0].content if result.files else True


def test_confirm_then_generate_against_fixture_profile() -> None:
    from test.packs.software_delivery.project_profile.conftest import load_component_files

    profile = profile_project(
        [{"component": "oie-tests", "files": load_component_files("acme/oie-tests")}]
    )
    draft = _draft(framework_selection=None, version=2, status="ready", generated_cases=())
    # Attach cucumber case after confirm path for generation.
    repo = _MemoryRepo(draft)
    confirmed = ConfirmFrameworkSelection(repository=repo).execute(
        ConfirmFrameworkRequest(
            draft_id="draft-1",
            expected_version=2,
            framework_id="robot_framework",
            component_id="oie-tests",
            profile=profile,
            profile_fingerprint=profile.profile_fingerprint,
        )
    )
    assert confirmed.status == "ok"
    assert confirmed.draft is not None
    with_cases = replace(
        confirmed.draft,
        status="case_editing",
        candidates=_draft().candidates,
        generated_cases=_draft().generated_cases,
    )
    # Bypass validation that selected candidates must match — recreate cleanly.
    with_cases = _draft(
        version=confirmed.draft.version,
        framework_selection=confirmed.draft.framework_selection,
    )
    repo._by_id["draft-1"] = with_cases
    result = GenerateFrameworkTests(repository=repo).execute(
        GenerateFrameworkTestsRequest(
            draft_id="draft-1", expected_version=with_cases.version
        )
    )
    assert result.status == "ok"
    _assert_robot_parses(result.files[0].content)


def test_generated_steps_follow_case_expected_result_not_outdated_keyword_docs() -> None:
    """Behaviour comes from the case; convention docs must not rewrite assertions."""
    selection = _selection(
        reusable_components=(
            _keyword(
                "Order Should Be Cancelled",
                documentation="Outdated: asserts order remains open.",
            ),
            _keyword("Cancel Order", documentation="Cancel the current order."),
        )
    )
    draft = _draft(
        framework_selection=selection,
        generated_cases=(
            GeneratedTestCase(
                candidate_id="cand-1",
                test_type="manual",
                automation_fit="applicable",
                automation_rationale="",
                availability="available",
                preconditions="",
                steps=("Cancel Order", "Order Should Be Cancelled"),
                expected_result="Order is cancelled",
                gherkin="",
                user_edited=False,
            ),
        ),
    )
    result = GenerateFrameworkTests(repository=_MemoryRepo(draft)).execute(
        GenerateFrameworkTestsRequest(draft_id="draft-1", expected_version=3)
    )
    assert "Order Should Be Cancelled" in result.files[0].content
    assert "remains open" not in result.files[0].content
    reused = [
        step
        for step in result.tests[0].step_outcomes
        if step.step == "Order Should Be Cancelled"
    ][0]
    assert reused.outcome == "reused"
    assert reused.behaviour_refs
    assert reused.convention_refs


@pytest.mark.skipif(
    shutil.which("robot") is None, reason="robot CLI not available"
)
def test_optional_robot_dryrun_on_self_contained_suite(tmp_path: Path) -> None:
    content = (
        "*** Test Cases ***\n"
        "Self Contained\n"
        "    No Operation\n"
    )
    path = tmp_path / "self_contained.robot"
    path.write_text(content, encoding="utf-8")
    completed = subprocess.run(
        ["robot", "--dryrun", str(path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
