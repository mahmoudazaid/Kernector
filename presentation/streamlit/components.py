"""Streamlit rendering helpers."""

from collections.abc import Mapping, Sequence
from typing import Any

import streamlit as st

from application.contracts import RunMeta
from composition.conversation_export import build_conversation_pdf
from domain.model_settings import SETTINGS
from domain.validation import is_off_topic
from presentation.streamlit.conversation_export import (
    conversation_to_csv,
    conversation_to_json,
    conversation_to_markdown,
    project_conversation_turns,
    project_single_turn,
    turns_for_pdf,
)
from presentation.streamlit.run_details import run_detail_lines


def render_reply(reply: str, off_topic_marker: str | None = None) -> None:
    if off_topic_marker and is_off_topic(reply, off_topic_marker):
        st.warning("This input does not match what the selected prompt expects.")
    st.markdown(reply)


def render_run_meta(result: RunMeta | None) -> None:
    """Collapsed Run details expander. ``None`` or empty projection draws nothing.

    History re-renders these rows on every Streamlit rerun, so absence must stay
    ordinary.
    """
    lines = run_detail_lines(result)
    if not lines:
        return
    with st.expander("Run details", expanded=False):
        for line in lines:
            st.caption(line)


def render_export_actions(
    content: str, filename_prefix: str, *, key_prefix: str
) -> None:
    st.download_button(
        "export tests as MD",
        data=content,
        file_name=f"{filename_prefix}.md",
        mime="text/markdown",
        key=f"download_{key_prefix}",
    )


def render_conversation_export_actions(
    session_messages: Sequence[Mapping[str, Any]],
    *,
    turn_index: int,
    filename_prefix: str,
    key_prefix: str,
) -> None:
    """Offer per-turn conversation downloads (MD, JSON, CSV, PDF)."""
    turns = project_single_turn(session_messages, turn_index)
    st.download_button(
        "export tests as MD",
        data=conversation_to_markdown(turns),
        file_name=f"{filename_prefix}.md",
        mime="text/markdown",
        key=f"download_{key_prefix}_md",
    )
    st.download_button(
        "export tests as JSON",
        data=conversation_to_json(turns),
        file_name=f"{filename_prefix}.json",
        mime="application/json",
        key=f"download_{key_prefix}_json",
    )
    st.download_button(
        "export tests as CSV",
        data=conversation_to_csv(turns),
        file_name=f"{filename_prefix}.csv",
        mime="text/csv",
        key=f"download_{key_prefix}_csv",
    )
    st.download_button(
        "export tests as PDF",
        data=build_conversation_pdf(turns_for_pdf(turns)),
        file_name=f"{filename_prefix}.pdf",
        mime="application/pdf",
        key=f"download_{key_prefix}_pdf",
    )


def render_full_conversation_export(
    session_messages: Sequence[Mapping[str, Any]],
) -> None:
    """Offer full-thread downloads when the session has exportable turns."""
    turns = project_conversation_turns(session_messages)
    if not turns:
        return
    st.download_button(
        "export tests as MD",
        data=conversation_to_markdown(turns),
        file_name="conversation.md",
        mime="text/markdown",
        key="download_conversation_md",
    )
    st.download_button(
        "export tests as JSON",
        data=conversation_to_json(turns),
        file_name="conversation.json",
        mime="application/json",
        key="download_conversation_json",
    )
    st.download_button(
        "export tests as CSV",
        data=conversation_to_csv(turns),
        file_name="conversation.csv",
        mime="text/csv",
        key="download_conversation_csv",
    )
    st.download_button(
        "export tests as PDF",
        data=build_conversation_pdf(turns_for_pdf(turns)),
        file_name="conversation.pdf",
        mime="application/pdf",
        key="download_conversation_pdf",
    )


def render_model_settings(provider: str) -> Mapping[str, object]:
    values: dict[str, object] = {}
    with st.expander("Model Settings", icon=":material/tune:"):
        st.caption("Defaults are safe. Change only what you need.")
        for setting in SETTINGS:
            if provider not in setting.providers:
                continue
            widget = st.slider if setting.widget == "slider" else st.number_input
            values[setting.key] = widget(
                setting.label,
                min_value=setting.min_value,
                max_value=setting.max_value,
                value=setting.default,
                step=setting.step,
                help=setting.help,
                key=f"setting_{provider}_{setting.key}",
            )
    return values
