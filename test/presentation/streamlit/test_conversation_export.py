"""Tests for conversation export projection and download widgets (#181)."""

from __future__ import annotations

import json

import pytest

from application.contracts import InvokeToolResponse, RunMeta
from presentation.streamlit.conversation_export import (
    conversation_to_csv,
    conversation_to_json,
    project_conversation_turns,
    project_single_turn,
)


def _messages() -> list[dict[str, object]]:
    return [
        {"role": "user", "content": "Score this risk"},
        {
            "role": "assistant",
            "content": "Risk is medium.",
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
        {"role": "user", "content": "Export cases"},
        {
            "role": "assistant",
            "content": "Here are cases.",
            "run": RunMeta(request_id="req-2", outcome="success"),
        },
    ]


def test_project_conversation_turns_skips_display_only_and_tool_payloads() -> None:
    turns = project_conversation_turns(_messages())
    assert len(turns) == 4
    assert [t.role for t in turns] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    joined = "\n".join(t.content for t in turns)
    assert "sk-leaked-payload" not in joined
    assert turns[1].request_id == "req-1"
    assert turns[1].tools == ("software_delivery.score_risk",)
    assert turns[1].timestamp == ""


def test_conversation_to_json_matches_known_fixture_literal() -> None:
    turns = project_conversation_turns(_messages())
    payload = conversation_to_json(turns)
    assert json.loads(payload) == [
        {
            "role": "user",
            "content": "Score this risk",
            "timestamp": "",
            "request_id": "",
            "tools": [],
        },
        {
            "role": "assistant",
            "content": "Risk is medium.",
            "timestamp": "",
            "request_id": "req-1",
            "tools": ["software_delivery.score_risk"],
        },
        {
            "role": "user",
            "content": "Export cases",
            "timestamp": "",
            "request_id": "",
            "tools": [],
        },
        {
            "role": "assistant",
            "content": "Here are cases.",
            "timestamp": "",
            "request_id": "req-2",
            "tools": [],
        },
    ]


def test_project_single_turn_returns_only_that_assistant_message() -> None:
    turns = project_single_turn(_messages(), 1)
    assert len(turns) == 1
    assert turns[0].role == "assistant"
    assert turns[0].content == "Risk is medium."
    assert turns[0].request_id == "req-1"


def test_render_conversation_export_actions_offers_json_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import presentation.streamlit.components as components_mod
    from presentation.streamlit.components import render_conversation_export_actions

    captured: list[dict[str, object]] = []

    def capture_download_button(*args: object, **kwargs: object) -> bool:
        label = args[0] if args else kwargs.get("label")
        captured.append(
            {
                "label": label,
                "data": kwargs.get("data"),
                "file_name": kwargs.get("file_name"),
                "mime": kwargs.get("mime"),
                "key": kwargs.get("key"),
            }
        )
        return True

    monkeypatch.setattr(components_mod.st, "download_button", capture_download_button)

    render_conversation_export_actions(
        _messages(),
        turn_index=1,
        filename_prefix="analysis_1",
        key_prefix="analysis_1",
    )

    json_buttons = [c for c in captured if c["mime"] == "application/json"]
    assert len(json_buttons) == 1
    button = json_buttons[0]
    assert button["label"] == "export tests as JSON"
    assert button["file_name"] == "analysis_1.json"
    assert button["key"] == "download_analysis_1_json"
    data = button["data"]
    assert isinstance(data, str)
    assert json.loads(data) == [
        {
            "role": "assistant",
            "content": "Risk is medium.",
            "timestamp": "",
            "request_id": "req-1",
            "tools": ["software_delivery.score_risk"],
        }
    ]


def test_conversation_to_csv_uses_known_header_and_escapes_commas() -> None:
    from presentation.streamlit.conversation_export import ExportTurn

    csv_text = conversation_to_csv(
        (
            ExportTurn(role="user", content="Hello, world"),
            ExportTurn(
                role="assistant",
                content="Risk is medium.",
                request_id="req-1",
            ),
        )
    )
    assert csv_text.splitlines() == [
        "role,content,timestamp,request_id",
        'user,"Hello, world",,',
        "assistant,Risk is medium.,,req-1",
    ]


def test_render_conversation_export_actions_offers_csv_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import presentation.streamlit.components as components_mod
    from presentation.streamlit.components import render_conversation_export_actions

    captured: list[dict[str, object]] = []

    def capture_download_button(*args: object, **kwargs: object) -> bool:
        label = args[0] if args else kwargs.get("label")
        captured.append(
            {
                "label": label,
                "file_name": kwargs.get("file_name"),
                "mime": kwargs.get("mime"),
                "key": kwargs.get("key"),
                "data": kwargs.get("data"),
            }
        )
        return True

    monkeypatch.setattr(components_mod.st, "download_button", capture_download_button)

    render_conversation_export_actions(
        _messages(),
        turn_index=1,
        filename_prefix="analysis_1",
        key_prefix="analysis_1",
    )

    csv_buttons = [c for c in captured if c["mime"] == "text/csv"]
    assert len(csv_buttons) == 1
    button = csv_buttons[0]
    assert button["label"] == "export tests as CSV"
    assert button["file_name"] == "analysis_1.csv"
    assert button["key"] == "download_analysis_1_csv"
    assert isinstance(button["data"], str)
    assert button["data"].startswith("role,content,timestamp,request_id\n")


def test_render_full_conversation_export_offers_all_format_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import presentation.streamlit.components as components_mod
    from presentation.streamlit.components import render_full_conversation_export

    keys: list[str] = []

    def capture_download_button(*args: object, **kwargs: object) -> bool:
        key = kwargs.get("key")
        assert isinstance(key, str)
        keys.append(key)
        return True

    monkeypatch.setattr(components_mod.st, "download_button", capture_download_button)

    render_full_conversation_export(_messages())

    assert "download_conversation_json" in keys
    assert "download_conversation_csv" in keys
    assert "download_conversation_md" in keys
    assert "download_conversation_pdf" in keys


def test_render_full_conversation_export_is_noop_for_empty_session(
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


def test_render_conversation_export_actions_offers_pdf_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import presentation.streamlit.components as components_mod
    from presentation.streamlit.components import render_conversation_export_actions

    captured: list[dict[str, object]] = []

    def capture_download_button(*args: object, **kwargs: object) -> bool:
        label = args[0] if args else kwargs.get("label")
        captured.append(
            {
                "label": label,
                "file_name": kwargs.get("file_name"),
                "mime": kwargs.get("mime"),
                "key": kwargs.get("key"),
                "data": kwargs.get("data"),
            }
        )
        return True

    monkeypatch.setattr(components_mod.st, "download_button", capture_download_button)

    render_conversation_export_actions(
        _messages(),
        turn_index=1,
        filename_prefix="analysis_1",
        key_prefix="analysis_1",
    )

    pdf_buttons = [c for c in captured if c["mime"] == "application/pdf"]
    assert len(pdf_buttons) == 1
    button = pdf_buttons[0]
    assert button["label"] == "export tests as PDF"
    assert button["file_name"] == "analysis_1.pdf"
    assert button["key"] == "download_analysis_1_pdf"
    assert isinstance(button["data"], (bytes, bytearray))
    assert button["data"].startswith(b"%PDF")


def test_render_conversation_export_actions_offers_md_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import presentation.streamlit.components as components_mod
    from presentation.streamlit.components import render_conversation_export_actions

    captured: list[dict[str, object]] = []

    def capture_download_button(*args: object, **kwargs: object) -> bool:
        label = args[0] if args else kwargs.get("label")
        captured.append(
            {
                "label": label,
                "file_name": kwargs.get("file_name"),
                "mime": kwargs.get("mime"),
                "key": kwargs.get("key"),
                "data": kwargs.get("data"),
            }
        )
        return True

    monkeypatch.setattr(components_mod.st, "download_button", capture_download_button)

    render_conversation_export_actions(
        _messages(),
        turn_index=1,
        filename_prefix="analysis_1",
        key_prefix="analysis_1",
    )

    md_buttons = [c for c in captured if c["mime"] == "text/markdown"]
    assert len(md_buttons) == 1
    button = md_buttons[0]
    assert button["label"] == "export tests as MD"
    assert button["file_name"] == "analysis_1.md"
    assert button["key"] == "download_analysis_1_md"
    assert isinstance(button["data"], str)
    assert "Risk is medium." in button["data"]


def test_two_historical_turns_use_distinct_keys_across_all_formats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import presentation.streamlit.components as components_mod
    from presentation.streamlit.components import render_conversation_export_actions

    keys: list[str] = []

    def capture_download_button(*args: object, **kwargs: object) -> bool:
        key = kwargs.get("key")
        assert isinstance(key, str)
        keys.append(key)
        return True

    monkeypatch.setattr(components_mod.st, "download_button", capture_download_button)

    messages = _messages()
    render_conversation_export_actions(
        messages,
        turn_index=1,
        filename_prefix="analysis_1",
        key_prefix="analysis_1",
    )
    render_conversation_export_actions(
        messages,
        turn_index=4,
        filename_prefix="analysis_4",
        key_prefix="analysis_4",
    )

    assert keys == [
        "download_analysis_1_md",
        "download_analysis_1_json",
        "download_analysis_1_csv",
        "download_analysis_1_pdf",
        "download_analysis_4_md",
        "download_analysis_4_json",
        "download_analysis_4_csv",
        "download_analysis_4_pdf",
    ]
    assert len(set(keys)) == 8


