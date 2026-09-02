"""Build a readable conversation transcript PDF (no secrets/tool payloads)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import BytesIO
from typing import Any

from fpdf import FPDF


def build_conversation_transcript_pdf(
    turns: Sequence[Mapping[str, Any]],
) -> bytes:
    """Render role/content turns as a plain PDF transcript.

    Callers must pass already-sanitized turns (role + content only). This
    function never reads tool payloads, settings, or other session fields.
    """
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(left=15, top=15, right=15)
    width = pdf.epw

    for turn in turns:
        role = str(turn.get("role", "")).strip() or "unknown"
        content = str(turn.get("content", ""))
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
