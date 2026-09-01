"""Behavior tests for Software Delivery composition views."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from composition.software_delivery_tools import (
    RiskFactorView,
    RiskScoreView,
    SoftwareDeliveryRunView,
    TestCaseView,
    TestCasesView,
    software_delivery_tools_enabled,
)
from composition.tool_runs import ToolCallView
from domain.knowledge import SourceReference


class _Settings:
    """Duck-typed stand-in: reads ``domain_tools.enabled_packs`` only."""

    def __init__(self, *packs: str) -> None:
        self.domain_tools = SimpleNamespace(enabled_packs=packs)


def _fixture_view() -> SoftwareDeliveryRunView:
    return SoftwareDeliveryRunView(
        summary="Scored risk and generated test cases.",
        calls=(
            ToolCallView(
                "software_delivery.risk_score",
                ok=True,
                summary="Scored risk at 62/100",
            ),
            ToolCallView(
                "software_delivery.generate_test_cases",
                ok=True,
                summary="Generated 1 test case",
            ),
        ),
        risk=RiskScoreView(
            score=62,
            level="high",
            rationale="Acceptance criteria are absent from a complete story.",
            factors=(
                RiskFactorView(
                    factor_id="missing_acceptance_criteria",
                    weight=30,
                    references=(SourceReference("SRS-2", "srs"),),
                ),
            ),
        ),
        test_cases=TestCasesView(
            output_style="steps",
            cases=(
                TestCaseView(
                    title="Lock the account after five failed MFA attempts",
                    steps=("Sign in with a valid password.", "Fail MFA five times."),
                    expected="The account is locked.",
                    references=(SourceReference("US-1", "user_story"),),
                ),
            ),
        ),
        markdown="# Test Cases\n",
    )


def test_fixture_view_carries_risk_test_cases_and_markdown() -> None:
    view = _fixture_view()

    assert view.risk is not None
    assert view.risk.score == 62
    assert view.test_cases is not None
    assert view.test_cases.cases[0].title.startswith("Lock the account")
    assert view.markdown.startswith("# Test Cases")
    assert all(isinstance(call, ToolCallView) for call in view.calls)
    assert all(not hasattr(call, "result") for call in view.calls)


def test_tool_renderers_are_absent_when_the_pack_is_disabled() -> None:
    assert software_delivery_tools_enabled(_Settings()) is False
    assert software_delivery_tools_enabled(_Settings("other-pack")) is False


def test_tool_renderers_may_be_shown_when_the_pack_is_enabled() -> None:
    assert software_delivery_tools_enabled(_Settings("software-delivery")) is True


def test_software_delivery_tools_module_stays_view_only() -> None:
    source = Path("composition/software_delivery_tools.py").read_text(encoding="utf-8")
    assert "import packs" not in source
    assert "from packs" not in source
    assert "retrieve" not in source.lower() or "no retrieval" in source.lower()
    assert "PackSoftwareDeliveryTools" not in source
    assert "run_view" not in source
