"""Contracts for framework-aware Test Design (#368)."""

from __future__ import annotations

import pytest

from packs.software_delivery.project_profile.models import (
    Convention,
    EvidenceRef,
    LineRange,
    ReusableComponent,
)
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.framework_contracts import (
    FRAMEWORK_RESULT_STATUSES,
    STEP_REUSE_OUTCOMES,
    FrameworkArtifactResult,
    FrameworkFile,
    FrameworkSelection,
    FrameworkTestTrace,
    StepOutcome,
)
from packs.software_delivery.test_design.models import TestCaseType


def _ref() -> EvidenceRef:
    return EvidenceRef(
        component="acme/oie-tests",
        path="resources/orders.resource",
        content_hash="abc",
        line_range=LineRange(1, 2),
    )


def _keyword() -> ReusableComponent:
    return ReusableComponent(
        component_id="kw:Cancel Order",
        kind="keyword",
        framework_id="robot_framework",
        signature="Cancel Order",
        path="resources/orders.resource",
        content_hash="abc",
        line_range=LineRange(10, 20),
        documentation="Cancels an order",
    )


def _convention() -> Convention:
    return Convention(
        name="test_folder",
        value="tests/",
        evidence_refs=(_ref(),),
    )


def test_test_type_cucumber_remains_gherkin_bdd_not_runtime() -> None:
    """``cucumber`` means a Gherkin BDD scenario, not a Cucumber runtime."""
    allowed: set[str] = set(__import__("typing").get_args(TestCaseType))
    assert allowed == {"manual", "cucumber"}
    assert "bdd" not in allowed


def test_framework_selection_stores_bounded_snapshot() -> None:
    selection = FrameworkSelection(
        component_id="acme/oie-tests",
        framework_id="robot_framework",
        profile_fingerprint="fp-1",
        evidence_origin="client_supplied",
        conventions=(_convention(),),
        reusable_components=(_keyword(),),
        confirmed_at_version=3,
    )
    assert selection.framework_id == "robot_framework"
    assert selection.reusable_components[0].signature == "Cancel Order"


def test_framework_selection_rejects_empty_framework_id() -> None:
    with pytest.raises(TestDesignValidationError, match="framework_id"):
        FrameworkSelection(
            component_id="acme/oie-tests",
            framework_id="  ",
            profile_fingerprint="fp-1",
            evidence_origin="client_supplied",
            conventions=(),
            reusable_components=(),
            confirmed_at_version=1,
        )


def test_vocabulary_keeps_syntax_framework_and_test_type_distinct() -> None:
    assert "gherkin" not in FRAMEWORK_RESULT_STATUSES
    assert "cucumber" not in FRAMEWORK_RESULT_STATUSES
    assert STEP_REUSE_OUTCOMES == frozenset(
        {"reused", "ambiguous", "implementation_required", "unsupported"}
    )
    assert FRAMEWORK_RESULT_STATUSES == frozenset(
        {
            "ok",
            "framework_choice_required",
            "profile_required",
            "unsupported_framework",
        }
    )


def test_framework_artifact_result_carries_files_and_traces() -> None:
    result = FrameworkArtifactResult(
        status="ok",
        framework_id="robot_framework",
        files=(
            FrameworkFile(
                filename="cancel_order.robot",
                suggested_path="tests/orders/cancel_order.robot",
                content="*** Test Cases ***\nCancel\n",
            ),
        ),
        tests=(
            FrameworkTestTrace(
                candidate_id="cand-1",
                evidence_refs=(("jira", "PROJ-1"),),
                step_outcomes=(
                    StepOutcome(
                        step="Cancel Order",
                        outcome="reused",
                        behaviour_refs=(("jira", "PROJ-1"),),
                        convention_refs=("kw:Cancel Order",),
                        component_id="kw:Cancel Order",
                    ),
                ),
            ),
        ),
        implementation_required=(),
        skipped=(),
        untrusted_model_output=False,
        evidence_origin="client_supplied",
    )
    assert result.status == "ok"
    assert result.files[0].suggested_path.endswith(".robot")


def test_unsupported_framework_result_has_no_executable_files() -> None:
    result = FrameworkArtifactResult(
        status="unsupported_framework",
        framework_id="playwright",
        files=(),
        tests=(),
        implementation_required=(),
        skipped=(),
        untrusted_model_output=False,
        evidence_origin="client_supplied",
    )
    assert result.files == ()
