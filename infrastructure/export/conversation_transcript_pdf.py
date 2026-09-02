"""Build a readable transcript PDF (Helvetica-safe Unicode)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import BytesIO
from typing import Any

from fpdf import FPDF

# Common punctuation models emit that Helvetica (latin-1) cannot encode.
_UNICODE_REPLACEMENTS = str.maketrans(
    {
        "\u2014": "-",  # em dash
        "\u2013": "-",  # en dash
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u00a0": " ",  # non-breaking space
    }
)


def _for_core_font(text: str) -> str:
    """Map text into Helvetica's latin-1 repertoire without raising."""
    translated = text.translate(_UNICODE_REPLACEMENTS)
    return translated.encode("latin-1", errors="replace").decode("latin-1")


def build_conversation_transcript_pdf(
    turns: Sequence[Mapping[str, Any]],
) -> bytes:
    """Render title/body turns as a plain PDF transcript.

    Callers must pass already-sanitized turns (role + content only). This
    function never reads tool payloads, settings, or other session fields.
    """
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(left=15, top=15, right=15)
    width = pdf.epw

    for turn in turns:
        role = _for_core_font(str(turn.get("role", "")).strip() or "unknown")
        content = _for_core_font(str(turn.get("content", "")))
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", style="B", size=12)
        pdf.multi_cell(width, 8, role)
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", size=12)
        pdf.multi_cell(width, 8, content)
        pdf.ln(4)

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()
