"""Streamlit panel for the enabled domain pack's tool run.

Widgets only: every decision, format and message comes from
``presentation.streamlit.tool_run``. Pack vocabulary is confined to this module
so shared app flow does not present one pack as the whole product — an
isolation the ``app.py`` source scan enforces.
"""

from __future__ import annotations

from collections.abc import Sequence

import streamlit as st

from application.errors import ConfigurationError
from composition import (
    SOFTWARE_DELIVERY_TEST_STYLES,
    RiskScoreView,
    Settings,
    TestCasesView,
    ToolCallView,
    build_software_delivery_tools,
    software_delivery_tools_enabled,
)
from domain.ports import ChatModel
from presentation.streamlit.components import render_export_actions
from presentation.streamlit.tool_run import (
    StoredToolRunResult,
    ToolRunContext,
    risk_factor_bullets,
    run_tool_turn,
    case_lines,
    tool_call_lines,
    tool_run_result_for_display,
)

TOOL_RUN_RESULT_KEY = "tool_run_result"


def _render_tool_calls(calls: Sequence[ToolCallView]) -> None:
    if not calls:
        return
    st.markdown("**Tool calls**")
    for line in tool_call_lines(calls):
        st.markdown(line)
    for call in calls:
        if not call.result:
            continue
        with st.expander(f"Raw result · {call.tool_name}"):
            st.code(call.result)


def _render_risk(risk: RiskScoreView) -> None:
    st.markdown("**Risk**")
    st.metric("Risk score", f"{risk.score}/100", help=f"Level: {risk.level}")
    st.markdown(risk.rationale)
    for bullet in risk_factor_bullets(risk.factors):
        st.markdown(bullet)


def _render_test_cases(test_cases: TestCasesView) -> None:
    st.markdown(f"**Test cases** ({test_cases.output_style})")
    for index, case in enumerate(test_cases.cases, start=1):
        with st.expander(f"{index}. {case.title}"):
            for line in case_lines(case):
                st.markdown(line)


def _render_markdown_export(markdown: str) -> None:
    st.markdown("**Markdown export**")
    with st.expander("Preview"):
        st.code(markdown, language="markdown")
    render_export_actions(markdown, "test_cases")


def render_tool_run(
    settings: Settings,
    chat_model: ChatModel,
    *,
    provider: str,
    model: str,
) -> None:
    """Run domain tools over retrieved evidence. Absent unless a pack is enabled."""
    if not software_delivery_tools_enabled(settings):
        return

    try:
        runner = build_software_delivery_tools(settings, chat_model=chat_model)
    except ConfigurationError as error:
        st.error(str(error))
        return

    st.subheader("Tool run")
    with st.form("tool_run"):
        target = st.text_input(
            "What should the tools assess?",
            help="Evidence is retrieved across every ingested source kind.",
        )
        generate_tests = st.checkbox(
            "Also generate test cases and a Markdown export", value=True
        )
        output_style = st.selectbox(
            "Test case style", options=list(SOFTWARE_DELIVERY_TEST_STYLES)
        )
        submitted = st.form_submit_button("Run tools")

    context = ToolRunContext(
        target=target,
        generate_tests=generate_tests,
        output_style=output_style,
        provider=provider,
        model=model,
    )

    if submitted:
        with st.spinner("Running tools..."):
            st.session_state[TOOL_RUN_RESULT_KEY] = StoredToolRunResult(
                context=context,
                result=run_tool_turn(
                    runner,
                    target=target,
                    generate_tests=generate_tests,
                    output_style=output_style,
                ),
            )

    result = tool_run_result_for_display(
        st.session_state.get(TOOL_RUN_RESULT_KEY), context=context
    )
    if result is None:
        return

    _render_tool_calls(result.calls)
    if not result.ok:
        st.error(result.message)
        return

    assert result.view is not None
    st.caption(result.view.summary)
    if result.view.risk is not None:
        _render_risk(result.view.risk)
    if result.view.test_cases is not None:
        _render_test_cases(result.view.test_cases)
    if result.view.markdown:
        _render_markdown_export(result.view.markdown)
