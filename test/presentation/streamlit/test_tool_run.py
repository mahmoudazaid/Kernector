"""Behavior tests for Software Delivery tool-result presentation seams."""

from __future__ import annotations

from pathlib import Path

import pytest

from composition import (
    RiskFactorView,
    RiskScoreView,
    SoftwareDeliveryRunView,
    TestCaseView,
    TestCasesView,
    ToolCallView,
)
from domain.knowledge import SourceReference
from presentation.streamlit.tool_run import (
    case_lines,
    risk_factor_bullets,
    tool_call_lines,
)


def _fixture_view() -> SoftwareDeliveryRunView:
    return SoftwareDeliveryRunView(
        summary="Scored risk, generated test cases, and exported Markdown.",
        calls=(
            ToolCallView(
                "software_delivery.risk_score",
                ok=True,
                summary="Scored risk at 62/100",
            ),
            ToolCallView("software_delivery.generate_test_cases", ok=False),
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


def test_tool_call_lines_show_name_status_and_authored_summary_only() -> None:
    calls = _fixture_view().calls

    assert tool_call_lines(calls) == (
        "- `software_delivery.risk_score` — succeeded — Scored risk at 62/100",
        "- `software_delivery.generate_test_cases` — failed",
    )
    rendered = " ".join(tool_call_lines(calls))
    assert '{"score"' not in rendered
    assert "sk-live-abc" not in rendered


def test_presentation_has_no_raw_to_summary_projection_helper() -> None:
    import presentation.streamlit.tool_run as helper_mod

    source = Path(helper_mod.__file__).read_text(encoding="utf-8")
    assert "bounded_tool_call_summary" not in source
    assert "from application.contracts import" not in source
    assert "InvokeToolResponse(" not in source


def test_no_calls_render_no_lines() -> None:
    assert tool_call_lines(()) == ()


def test_risk_factor_bullets_carry_every_supporting_reference() -> None:
    factors = (
        RiskFactorView(
            factor_id="missing_acceptance_criteria",
            weight=30,
            references=(
                SourceReference("SRS-2", "srs"),
                SourceReference("US-1", "user_story"),
            ),
        ),
    )

    assert risk_factor_bullets(factors) == (
        "- `missing_acceptance_criteria` (weight 30) — `SRS-2` (srs), "
        "`US-1` (user_story)",
    )


def test_case_lines_number_the_steps_and_cite_the_sources() -> None:
    case = TestCaseView(
        title="Lock the account after five failed MFA attempts",
        steps=("Sign in with a valid password.", "Fail MFA five times."),
        expected="The account is locked.",
        references=(SourceReference("US-1", "user_story"),),
    )

    assert case_lines(case) == (
        "1. Sign in with a valid password.",
        "2. Fail MFA five times.",
        "",
        "**Expected:** The account is locked.",
        "**References:** `US-1` (user_story)",
    )


def test_tool_run_modules_reach_the_pack_only_through_composition() -> None:
    import presentation.streamlit.tool_run as helper_mod
    import presentation.streamlit.tool_run_panel as panel_mod

    for module in (helper_mod, panel_mod):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "import packs" not in source
        assert "from packs" not in source
        assert "infrastructure" not in source
        assert "from composition import" in source
        assert "build_software_delivery_tools" not in source
        assert "run_tool_turn" not in source


def test_shared_app_flow_does_not_name_the_pack_or_tool_run_form() -> None:
    import presentation.streamlit.app as app_mod

    source = Path(app_mod.__file__).read_text(encoding="utf-8")
    assert "software_delivery" not in source
    assert "risk_score" not in source
    assert "render_tool_run" not in source
    assert "TOOL_RUN_RESULT_KEY" not in source
    assert "tool_run" not in source


def test_composition_has_no_parallel_tool_run_entry_point() -> None:
    import composition
    import composition.container as container_mod

    assert not hasattr(composition, "build_software_delivery_tools")
    source = Path(container_mod.__file__).read_text(encoding="utf-8")
    assert "build_software_delivery_tools" not in source
    assert "PackSoftwareDeliveryTools" not in source


def test_ask_turn_still_ignores_tool_outputs() -> None:
    """#170-owned chat integration stays untouched in this PR."""
    import presentation.streamlit.ask_turn as ask_turn_mod

    source = Path(ask_turn_mod.__file__).read_text(encoding="utf-8")
    assert "tool_outputs" not in source
    assert "render_software_delivery" not in source
    assert "SoftwareDeliveryRunView" not in source


def test_architecture_docs_do_not_store_typed_views_on_ask_response() -> None:
    architecture = Path("ARCHITECTURE.md").read_text(encoding="utf-8")
    sd_tools = Path("composition/software_delivery_tools.py").read_text(encoding="utf-8")

    assert "tool_outputs`` with typed views" not in architecture
    assert "projection onto these views" not in architecture
    assert "not** stored on ``AskResponse.tool_outputs``" in sd_tools
    assert "opaque ``InvokeToolResponse``" in architecture


def test_app_does_not_wire_tool_outputs_to_renderers() -> None:
    import presentation.streamlit.app as app_mod

    source = Path(app_mod.__file__).read_text(encoding="utf-8")
    assert "tool_outputs" not in source
    assert "render_software_delivery_tool_results" not in source


def test_render_software_delivery_tool_results_accepts_fixture_view() -> None:
    from presentation.streamlit.tool_run_panel import render_software_delivery_tool_results

    render_software_delivery_tool_results(_fixture_view())
