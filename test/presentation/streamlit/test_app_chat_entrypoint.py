"""Unified chat entrypoint: no Mode selector, no standalone workflow form (#173)."""

from pathlib import Path


def _app_source() -> str:
    import presentation.streamlit.app as app_mod

    return Path(app_mod.__file__).read_text(encoding="utf-8")


def test_streamlit_app_has_no_mode_selector() -> None:
    """AC1: the app starts with no preselected Mode control."""
    source = _app_source()

    assert 'st.selectbox(\n        "Mode"' not in source
    assert 'selectbox(\n        "Mode"' not in source
    assert '"Mode"' not in source
    assert "mode_options" not in source
    assert "default_mode_index" not in source
    assert "from presentation.streamlit.modes" not in source


def test_streamlit_app_chat_runs_without_preselected_prompt() -> None:
    """Chat is intent-first: presentation does not drive a Mode-chosen prompt."""
    source = _app_source()

    assert "run_ask_turn" in source
    assert "build_tool_augmented_ask" in source
    # PromptRepository stays wired for #149; the UI must not select a Mode.
    assert "build_prompt_repository" in source
    assert "prompt_repository=repository" in source
    # No Mode-selected prompt flows from sidebar into the chat turn.
    assert "state.prompt_key" not in source
    assert "prompts[state.prompt_key]" not in source
    assert "prompts[prompt_key]" not in source


def test_streamlit_app_routes_analysis_through_chat_not_a_form() -> None:
    """Requirements analysis is chat-only; no pack imports in presentation."""
    source = _app_source()

    assert "import packs" not in source
    assert "from packs" not in source
    assert "software_delivery" not in source
    assert "AnalyzeRequirements" not in source
    assert "build_analyze_requirements" not in source
    assert "requirements_analysis_enabled" not in source
    assert "run_analysis_turn" not in source
    assert "requirements_analysis" not in source
    assert "build_tool_augmented_ask" in source
