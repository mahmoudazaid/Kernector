"""Tests for Software Delivery test-cases multi-format export (#181)."""

from __future__ import annotations

import json

import pytest

from composition import TestCaseView, TestCasesView
from domain.knowledge import SourceReference
from presentation.streamlit.cases_export import (
    cases_pdf_turns,
    cases_to_csv,
    cases_to_json,
)


def _cases() -> TestCasesView:
    return TestCasesView(
        output_style="numbered",
        cases=(
            TestCaseView(
                title="Login succeeds",
                steps=("Open login", "Submit valid credentials"),
                expected="User lands on home",
                references=(
                    SourceReference(
                        source_id="US-1",
                        source_type="user_story",
                    ),
                ),
            ),
        ),
    )


def test_cases_to_json_matches_known_fixture_literal() -> None:
    payload = cases_to_json("# unused\n", _cases())
    assert json.loads(payload) == {
        "output_style": "numbered",
        "cases": [
            {
                "title": "Login succeeds",
                "steps": ["Open login", "Submit valid credentials"],
                "expected": "User lands on home",
                "references": [
                    {"source_id": "US-1", "source_type": "user_story"},
                ],
            }
        ],
    }


def test_cases_to_json_falls_back_to_markdown_wrapper() -> None:
    payload = cases_to_json("# Test Cases\n", None)
    assert json.loads(payload) == {"markdown": "# Test Cases\n"}


def test_cases_to_csv_uses_known_header_and_escapes_commas() -> None:
    cases = TestCasesView(
        output_style="numbered",
        cases=(
            TestCaseView(
                title="Hello, world",
                steps=("step one",),
                expected="ok",
                references=(),
            ),
        ),
    )
    csv_text = cases_to_csv("# unused\n", cases)
    assert csv_text.splitlines() == [
        "title,steps,expected,references",
        '"Hello, world",step one,ok,',
    ]


def test_cases_pdf_turns_use_structured_cases_when_present() -> None:
    turns = cases_pdf_turns("# unused\n", _cases())
    assert turns == (
        {
            "role": "1. Login succeeds",
            "content": (
                "1. Open login\n"
                "2. Submit valid credentials\n\n"
                "Expected: User lands on home\n"
                "References: US-1 (user_story)"
            ),
        },
    )


def test_render_test_cases_export_actions_offers_all_formats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import presentation.streamlit.components as components_mod
    from presentation.streamlit.components import render_test_cases_export_actions

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

    render_test_cases_export_actions(
        "# Test Cases\n",
        key_prefix="export_1",
        test_cases=_cases(),
    )

    by_mime = {c["mime"]: c for c in captured}
    assert by_mime["text/markdown"]["label"] == "export tests as MD"
    assert by_mime["text/markdown"]["key"] == "download_export_1_md"
    assert by_mime["application/json"]["label"] == "export tests as JSON"
    assert by_mime["application/json"]["key"] == "download_export_1_json"
    assert by_mime["text/csv"]["label"] == "export tests as CSV"
    assert by_mime["text/csv"]["key"] == "download_export_1_csv"
    assert by_mime["application/pdf"]["label"] == "export tests as PDF"
    assert by_mime["application/pdf"]["key"] == "download_export_1_pdf"
    assert isinstance(by_mime["application/pdf"]["data"], (bytes, bytearray))
    assert by_mime["application/pdf"]["data"].startswith(b"%PDF")


def test_render_test_cases_export_pdf_survives_em_dash_in_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import presentation.streamlit.components as components_mod
    from presentation.streamlit.components import render_test_cases_export_actions

    captured: list[dict[str, object]] = []

    def capture_download_button(*args: object, **kwargs: object) -> bool:
        captured.append({"mime": kwargs.get("mime"), "data": kwargs.get("data")})
        return True

    monkeypatch.setattr(components_mod.st, "download_button", capture_download_button)

    render_test_cases_export_actions(
        "# Cases — with “quotes”…\n",
        key_prefix="export_unicode",
    )

    pdf = next(c for c in captured if c["mime"] == "application/pdf")
    assert pdf["data"].startswith(b"%PDF")
