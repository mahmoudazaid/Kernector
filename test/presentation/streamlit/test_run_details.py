"""Tests for safe Run details projection (no Streamlit widget rendering)."""

from __future__ import annotations

from pathlib import Path

from application.contracts import RunMeta
from domain.models import Usage
from presentation.streamlit.run_details import run_detail_lines


def test_run_detail_lines_empty_for_none() -> None:
    assert run_detail_lines(None) == ()


def test_run_detail_lines_omits_missing_fields() -> None:
    lines = run_detail_lines(RunMeta(request_id="req-1", outcome="success"))
    assert lines == ("Request ID: req-1", "Outcome: success")


def test_run_detail_lines_includes_issue_fields_when_present() -> None:
    lines = run_detail_lines(
        RunMeta(
            request_id="req-abc",
            outcome="success",
            latency_ms=12,
            model="test-model",
            usage=Usage(prompt_tokens=3, completion_tokens=7, total_tokens=10),
            pack="software-delivery",
            hit_count=2,
            tools=("score_risk", "generate_tests"),
            path="tools",
            prompt_key="secret-prompt-body-must-not-appear",
            settings={"temperature": 0.1},
            error_type="ProviderError",
        )
    )
    joined = "\n".join(lines)
    assert "Request ID: req-abc" in joined
    assert "Outcome: success" in joined
    assert "Latency: 12ms" in joined
    assert "Model: test-model" in joined
    assert "Tokens: 10" in joined
    assert "Pack: software-delivery" in joined
    assert "Retrieval hits: 2" in joined
    assert "Tools: score_risk, generate_tests" in joined
    assert "temperature" not in joined
    assert "secret-prompt-body" not in joined
    assert "ProviderError" not in joined
    assert "Path:" not in joined
    assert "prompt_key" not in joined


def test_run_detail_lines_never_include_sensitive_payloads() -> None:
    meta = RunMeta(
        request_id="req-safe",
        outcome="error",
        error_type="ProviderError",
        tools=("score_risk",),
    )
    joined = "\n".join(run_detail_lines(meta))
    assert "sk-leaked" not in joined
    assert "exception message" not in joined
    assert "ProviderError" not in joined
    assert "Tools: score_risk" in joined


def test_render_run_meta_uses_collapsed_run_details_expander() -> None:
    source = Path("presentation/streamlit/components.py").read_text(encoding="utf-8")
    assert 'st.expander("Run details"' in source
    assert "expanded=False" in source
    assert "run_detail_lines" in source


def _app_source() -> str:
    return Path("presentation/streamlit/app.py").read_text(encoding="utf-8")


def _block_between(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    stop = source.index(end, begin)
    return source[begin:stop]


def test_successful_history_turn_renders_run_details_after_reply_and_outputs() -> None:
    """History success: reply → citations → tools → projected → Run details → export."""
    history = _block_between(_app_source(), "def _render_history()", "def _handle_input(")
    assistant = _block_between(
        history,
        'if message["role"] == "assistant":',
        'else:\n                st.markdown(message["content"])',
    )
    reply_at = assistant.index("render_reply(")
    citations_at = assistant.index("_render_citations(")
    tools_at = assistant.index("_render_tool_outputs(")
    projected_at = assistant.index("render_projected_results(")
    run_at = assistant.index("render_run_meta(")
    export_at = assistant.index("render_export_actions(")
    assert reply_at < citations_at < tools_at < projected_at < run_at < export_at


def test_successful_live_turn_renders_run_details_after_reply_and_outputs() -> None:
    """Live success: reply → citations → tools → projected → Run details → export."""
    handle = _block_between(_app_source(), "def _handle_input(", "_ACTION_MESSAGE_KEY")
    success = handle.split("assert response is not None", 1)[1]
    reply_at = success.index("render_reply(")
    citations_at = success.index("_render_citations(")
    tools_at = success.index("_render_tool_outputs(")
    projected_at = success.index("render_projected_results(")
    run_at = success.index("render_run_meta(")
    export_at = success.index("render_export_actions(")
    assert reply_at < citations_at < tools_at < projected_at < run_at < export_at
    # Must not also render Run details before the reply on the success path.
    before_reply = success[:reply_at]
    assert "render_run_meta(" not in before_reply


def test_failed_turn_keeps_error_before_run_details() -> None:
    """Operational failure: st.error then Run details (live and history)."""
    source = _app_source()
    history = _block_between(source, "def _render_history()", "def _handle_input(")
    display_only = _block_between(
        history,
        'if message.get("display_only"):',
        'if message["role"] == "assistant":',
    )
    assert display_only.index("st.error(") < display_only.index("render_run_meta(")

    handle = _block_between(source, "def _handle_input(", "_ACTION_MESSAGE_KEY")
    failure = _block_between(handle, "if not result.ok:", "response = result.response")
    assert failure.index("st.error(") < failure.index("render_run_meta(")
