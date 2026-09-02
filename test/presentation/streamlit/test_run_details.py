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
