"""Tests for conversation transcript PDF generation."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from infrastructure.export.conversation_transcript_pdf import (
    build_conversation_transcript_pdf,
)


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_build_conversation_transcript_pdf_starts_with_pdf_header() -> None:
    pdf = build_conversation_transcript_pdf(
        (
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        )
    )
    assert pdf.startswith(b"%PDF")


def test_build_conversation_transcript_pdf_includes_roles_and_content() -> None:
    pdf = build_conversation_transcript_pdf(
        (
            {"role": "user", "content": "Score this risk"},
            {"role": "assistant", "content": "Risk is medium."},
        )
    )
    text = _pdf_text(pdf)
    assert "user" in text.lower()
    assert "assistant" in text.lower()
    assert "Score this risk" in text
    assert "Risk is medium." in text


def test_build_conversation_transcript_pdf_omits_secret_payload_text() -> None:
    pdf = build_conversation_transcript_pdf(
        ({"role": "assistant", "content": "Risk is medium."},)
    )
    text = _pdf_text(pdf)
    assert "sk-leaked-payload" not in text
    assert '{"secret"' not in text


def test_build_conversation_transcript_pdf_keeps_unicode_readable() -> None:
    pdf = build_conversation_transcript_pdf(
        (
            {
                "role": "assistant",
                "content": "Risk is medium — “watch auth” paths… Привет",
            },
        )
    )
    assert pdf.startswith(b"%PDF")
    text = _pdf_text(pdf)
    assert "Risk is medium" in text
    assert "watch auth" in text
    assert "—" in text
    assert "Привет" in text
    # Must not collapse smart punctuation / Cyrillic to replacement marks.
    assert "\ufffd" not in text
