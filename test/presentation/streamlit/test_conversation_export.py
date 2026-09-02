"""Tests for pack-agnostic conversation export (#181)."""

from __future__ import annotations

import csv
import io
import json
from io import BytesIO

import pytest
from pypdf import PdfReader

from application.contracts import InvokeToolResponse, RunMeta
from presentation.streamlit.conversation_export import (
    conversation_to_csv,
    conversation_to_json,
    conversation_to_markdown,
    neutralize_csv_formula,
    project_conversation_turns,
    project_single_turn,
)


def _messages() -> list[dict[str, object]]:
    return [
        {"role": "user", "content": "What is the PTO policy?"},
        {
            "role": "assistant",
            "content": "Request PTO ten business days ahead.",
            "tool_outputs": (
                InvokeToolResponse(
                    "software_delivery.score_risk",
                    '{"secret":"sk-leaked-payload"}',
                ),
            ),
            "run": RunMeta(
                request_id="req-1",
                outcome="success",
                tools=("software_delivery.score_risk",),
                settings={"temperature": 0.1},
                prompt_key="secret-prompt",
            ),
        },
        {
            "role": "assistant",
            "content": "Something went wrong.",
            "display_only": True,
        },
        {"role": "user", "content": "Thanks"},
        {
            "role": "assistant",
            "content": "You're welcome — “anytime”…",
        },
    ]


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_project_conversation_skips_display_only_and_tool_payloads() -> None:
    turns = project_conversation_turns(_messages())
    assert [t.role for t in turns] == ["user", "assistant", "user", "assistant"]
    joined = "\n".join(t.content for t in turns)
    assert "sk-leaked-payload" not in joined
    assert "secret-prompt" not in joined
    assert "temperature" not in joined
    assert all(hasattr(t, "timestamp") for t in turns)
    assert not any(hasattr(t, "request_id") for t in turns)


def test_conversation_to_json_matches_known_literal() -> None:
    turns = project_conversation_turns(_messages()[:2])
    assert json.loads(conversation_to_json(turns)) == [
        {
            "role": "user",
            "content": "What is the PTO policy?",
            "timestamp": "",
        },
        {
            "role": "assistant",
            "content": "Request PTO ten business days ahead.",
            "timestamp": "",
        },
    ]


def test_project_single_turn_exports_selected_assistant_only() -> None:
    turns = project_single_turn(_messages(), 1)
    assert len(turns) == 1
    assert turns[0].content == "Request PTO ten business days ahead."


def test_conversation_to_markdown_includes_roles() -> None:
    md = conversation_to_markdown(project_conversation_turns(_messages()[:2]))
    assert "### user" in md
    assert "### assistant" in md
    assert "What is the PTO policy?" in md


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("=1+1", "'=1+1"),
        ("+cmd", "'+cmd"),
        ("-1+1", "'-1+1"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tTAB", "'\tTAB"),
        ("\rCR", "'\rCR"),
        ("\nLF", "'\nLF"),
        ("safe", "safe"),
        ("hello, world", "hello, world"),
    ],
)
def test_neutralize_csv_formula_prefixes(raw: str, expected: str) -> None:
    assert neutralize_csv_formula(raw) == expected


def test_conversation_to_csv_neutralizes_formulas_and_escapes() -> None:
    from presentation.streamlit.conversation_export import ExportTurn

    csv_text = conversation_to_csv(
        (
            ExportTurn(role="user", content="=CMD()"),
            ExportTurn(role="assistant", content='He said "hi", then left'),
            ExportTurn(role="user", content="line1\nline2", timestamp="+now"),
        )
    )
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows[0] == ["role", "content", "timestamp"]
    assert rows[1] == ["user", "'=CMD()", ""]
    assert rows[2] == ["assistant", 'He said "hi", then left', ""]
    assert rows[3][0] == "user"
    assert rows[3][1] == "line1\nline2"
    assert rows[3][2] == "'+now"


def test_render_conversation_export_offers_all_four_formats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import presentation.streamlit.components as components_mod
    from presentation.streamlit.components import render_conversation_export_actions

    captured: list[dict[str, object]] = []

    def capture(*args: object, **kwargs: object) -> bool:
        label = args[0] if args else kwargs.get("label")
        captured.append(
            {
                "label": label,
                "mime": kwargs.get("mime"),
                "key": kwargs.get("key"),
                "file_name": kwargs.get("file_name"),
                "data": kwargs.get("data"),
            }
        )
        return True

    monkeypatch.setattr(components_mod.st, "download_button", capture)
    render_conversation_export_actions(
        _messages(),
        turn_index=None,
        filename_prefix="conversation",
        key_prefix="conversation",
    )
    mimes = {c["mime"] for c in captured}
    assert mimes == {
        "text/markdown",
        "application/json",
        "text/csv",
        "application/pdf",
    }
    assert {c["key"] for c in captured} == {
        "download_conversation_md",
        "download_conversation_json",
        "download_conversation_csv",
        "download_conversation_pdf",
    }
    pdf = next(c for c in captured if c["mime"] == "application/pdf")
    assert isinstance(pdf["data"], (bytes, bytearray))
    assert pdf["data"].startswith(b"%PDF")
    text = _pdf_text(bytes(pdf["data"]))
    assert "PTO" in text
    assert "anytime" in text or "You’re welcome" in text or "welcome" in text


def test_selected_assistant_turn_export_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import presentation.streamlit.components as components_mod
    from presentation.streamlit.components import render_conversation_export_actions

    keys: list[str] = []

    def capture(*args: object, **kwargs: object) -> bool:
        key = kwargs.get("key")
        assert isinstance(key, str)
        keys.append(key)
        return True

    monkeypatch.setattr(components_mod.st, "download_button", capture)
    render_conversation_export_actions(
        _messages(),
        turn_index=1,
        filename_prefix="analysis_1",
        key_prefix="analysis_1",
    )
    assert keys == [
        "download_analysis_1_md",
        "download_analysis_1_json",
        "download_analysis_1_csv",
        "download_analysis_1_pdf",
    ]
    json_btn = None

    captured: list[dict[str, object]] = []

    def capture2(*args: object, **kwargs: object) -> bool:
        captured.append({"mime": kwargs.get("mime"), "data": kwargs.get("data")})
        return True

    monkeypatch.setattr(components_mod.st, "download_button", capture2)
    render_conversation_export_actions(
        _messages(),
        turn_index=1,
        filename_prefix="analysis_1",
        key_prefix="analysis_1b",
    )
    json_btn = next(c for c in captured if c["mime"] == "application/json")
    assert json.loads(json_btn["data"]) == [
        {
            "role": "assistant",
            "content": "Request PTO ten business days ahead.",
            "timestamp": "",
        }
    ]


def test_history_and_live_export_keys_do_not_collide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import presentation.streamlit.components as components_mod
    from presentation.streamlit.components import render_conversation_export_actions

    keys: list[str] = []

    def capture(*args: object, **kwargs: object) -> bool:
        key = kwargs.get("key")
        assert isinstance(key, str)
        keys.append(key)
        return True

    monkeypatch.setattr(components_mod.st, "download_button", capture)
    messages = _messages()
    render_conversation_export_actions(
        messages,
        turn_index=1,
        filename_prefix="analysis_1",
        key_prefix="analysis_1",
    )
    live = [
        *messages,
        {"role": "assistant", "content": "Live answer"},
    ]
    render_conversation_export_actions(
        live,
        turn_index=len(messages),
        filename_prefix=f"analysis_{len(messages)}",
        key_prefix=f"analysis_{len(messages)}",
    )
    assert len(keys) == 8
    assert len(set(keys)) == 8
    assert "download_analysis_1_md" in keys
    assert f"download_analysis_{len(messages)}_pdf" in keys


def test_empty_session_renders_no_conversation_export_buttons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import presentation.streamlit.components as components_mod
    from presentation.streamlit.components import render_full_conversation_export

    called = False

    def boom(*args: object, **kwargs: object) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(components_mod.st, "download_button", boom)
    render_full_conversation_export([])
    assert called is False


def test_unicode_pdf_preserves_smart_punctuation_and_non_latin() -> None:
    from composition.conversation_export import build_conversation_pdf

    pdf = build_conversation_pdf(
        (
            {
                "role": "assistant",
                "content": "Welcome — “Привет” and café… Ελληνικά",
            },
        )
    )
    assert pdf.startswith(b"%PDF")
    text = _pdf_text(pdf)
    assert "Welcome" in text
    assert "—" in text
    assert "Привет" in text
    assert "café" in text
    assert "Ελληνικά" in text
    assert "\ufffd" not in text
