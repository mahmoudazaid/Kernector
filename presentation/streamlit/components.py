"""Streamlit rendering helpers."""

from collections.abc import Mapping

import streamlit as st

from application.contracts import RunMeta
from domain.model_settings import SETTINGS
from domain.validation import is_off_topic
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


def render_export_actions(content: str, filename_prefix: str) -> None:
    st.download_button(
        "Download output",
        data=content,
        file_name=f"{filename_prefix}.md",
        mime="text/markdown",
        key=f"download_{filename_prefix}",
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
