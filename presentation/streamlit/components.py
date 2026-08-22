"""Streamlit rendering helpers."""

from collections.abc import Mapping

import streamlit as st

from domain.model_settings import SETTINGS
from domain.models import AskResult
from domain.validation import is_off_topic


def render_reply(reply: str, off_topic_marker: str | None = None) -> None:
    if off_topic_marker and is_off_topic(reply, off_topic_marker):
        st.warning("This input does not match what the selected prompt expects.")
    st.markdown(reply)


def render_run_meta(result: AskResult) -> None:
    bits = []

    if result.model:
        bits.append(f"Model: {result.model}")

    if result.latency_ms is not None:
        bits.append(f"Latency: {result.latency_ms}ms")

    usage = result.usage
    if usage:
        if usage.total_tokens is not None:
            bits.append(f"Tokens: {usage.total_tokens}")
        elif usage.prompt_tokens is not None and usage.completion_tokens is not None:
            bits.append(
                f"Tokens: {usage.prompt_tokens} in / {usage.completion_tokens} out"
            )
        if usage.cost is not None:
            bits.append(f"Cost: ${usage.cost}")

    if result.settings:
        bits.append(" · ".join(f"{k}={v}" for k, v in result.settings.items()))

    if bits:
        st.caption(" | ".join(bits))


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
