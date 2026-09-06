"""Shared ``SoftwareDeliveryRunView`` builders for presentation/composition tests.

Not collected by pytest: the basename lacks the ``test_`` prefix.
"""

from __future__ import annotations

from dataclasses import replace

from composition.software_delivery_tools import (
    RiskFactorView,
    RiskScoreView,
    SoftwareDeliveryRunView,
    TestCaseView,
    TestCasesView,
)
from composition.tool_runs import ToolCallView
from domain.knowledge import SourceReference


def software_delivery_run_view(**changes: object) -> SoftwareDeliveryRunView:
    """Return a populated run view; pass dataclass fields to override.

    Defaults cover multi-element ``calls``, ``factors``, ``cases``, ``steps``,
    and ``references`` so projection tests can pin ordering and multiplicity.
    """
    view = SoftwareDeliveryRunView(
        summary="Scored risk and generated cases.",
        calls=(
            ToolCallView(
                "software_delivery.risk_score",
                ok=True,
                summary="Scored risk at 62/100",
            ),
            ToolCallView(
                "software_delivery.generate_test_cases",
                ok=True,
                summary="Generated 2 test cases",
            ),
        ),
        risk=RiskScoreView(
            score=62,
            level="medium",
            rationale="Model identified moderate security concerns in the codebase",
            factors=(
                RiskFactorView(
                    factor_id="auth-surface",
                    weight=3,
                    references=(
                        SourceReference("doc-1", "pdf"),
                        SourceReference("SRS-2", "srs"),
                    ),
                ),
                RiskFactorView(
                    factor_id="missing_acceptance_criteria",
                    weight=30,
                    references=(SourceReference("US-1", "user_story"),),
                ),
            ),
        ),
        test_cases=TestCasesView(
            output_style="steps",
            cases=(
                TestCaseView(
                    title="Lock after five failures",
                    steps=(
                        "Sign in with a valid password.",
                        "Fail MFA five times.",
                    ),
                    expected="Account locked.",
                    references=(SourceReference("US-1", "user_story"),),
                ),
                TestCaseView(
                    title="Require MFA on a new device",
                    steps=("Sign in from an unknown device.",),
                    expected="MFA challenge is issued.",
                    references=(SourceReference("AUTH-101", "user_story"),),
                ),
            ),
        ),
        markdown="# Test Cases\n",
    )
    return replace(view, **changes)
