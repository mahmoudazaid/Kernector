"""Streamlit renderers for Software Delivery tool-run results.

Widgets only: accepts ``SoftwareDeliveryRunView`` from test fixtures or from the
#178 composition projection (via ``render_projected_results``) — not from
``AskResponse.tool_outputs`` directly. No tool invocation, retrieval, or
orchestration lives here.
"""

from __future__ import annotations

from collections.abc import Sequence

import streamlit as st

from composition import (
    RiskScoreView,
    SoftwareDeliveryRunView,
    TestCasesView,
    ToolCallView,
)
from presentation.streamlit.components import render_test_cases_export_actions
from presentation.streamlit.tool_run import (
    case_lines,
    risk_factor_bullets,
    tool_call_lines,
)


def render_tool_call_envelope(calls: Sequence[ToolCallView]) -> None:
    """Show each tool name, status, and authored summary — never raw payloads."""
    if not calls:
        return
    st.markdown("**Tool calls**")
    for line in tool_call_lines(calls):
        st.markdown(line)


def render_risk_score(risk: RiskScoreView) -> None:
    st.markdown("**Risk**")
    st.metric("Risk score", f"{risk.score}/100", help=f"Level: {risk.level}")
    st.markdown(risk.rationale)
    for bullet in risk_factor_bullets(risk.factors):
        st.markdown(bullet)


def render_test_cases(test_cases: TestCasesView) -> None:
    st.markdown(f"**Test cases** ({test_cases.output_style})")
    for index, case in enumerate(test_cases.cases, start=1):
        with st.expander(f"{index}. {case.title}"):
            for line in case_lines(case):
                st.markdown(line)


def render_markdown_export(
    markdown: str,
    *,
    key_prefix: str,
    filename_prefix: str = "test_cases",
    test_cases: TestCasesView | None = None,
) -> None:
    st.markdown("**Test cases export**")
    with st.expander("Preview"):
        st.code(markdown, language="markdown")
    render_test_cases_export_actions(
        markdown,
        key_prefix=key_prefix,
        filename_prefix=filename_prefix,
        test_cases=test_cases,
    )


def render_software_delivery_tool_results(
    view: SoftwareDeliveryRunView, *, key_prefix: str
) -> None:
    """Render a complete Software Delivery tool run from typed views only."""
    render_tool_call_envelope(view.calls)
    if view.summary:
        st.caption(view.summary)
    if view.risk is not None:
        render_risk_score(view.risk)
    if view.test_cases is not None:
        render_test_cases(view.test_cases)
    if view.markdown:
        render_markdown_export(
            view.markdown,
            key_prefix=key_prefix,
            test_cases=view.test_cases,
        )
