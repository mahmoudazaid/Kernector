"""Build a readable conversation transcript PDF with a bundled Unicode font."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path
from typing import Any

from fpdf import FPDF

_FONTS_DIR = Path(__file__).resolve().parent / "fonts"
_FONT_REGULAR = _FONTS_DIR / "DejaVuSans.ttf"
_FONT_BOLD = _FONTS_DIR / "DejaVuSans-Bold.ttf"
_FONT_FAMILY = "DejaVu"


def build_conversation_transcript_pdf(
    turns: Sequence[Mapping[str, Any]],
) -> bytes:
    """Render role/content turns as a Unicode PDF transcript.

    Callers must pass already-sanitized turns (role + content only). This
    function never reads tool payloads, settings, or other session fields.
    Uses the vendored DejaVu Sans font (no host-font dependency).
    """
    if not _FONT_REGULAR.is_file() or not _FONT_BOLD.is_file():
        raise FileNotFoundError(
            f"Bundled DejaVu fonts missing under {_FONTS_DIR}"
        )

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font(_FONT_FAMILY, style="", fname=str(_FONT_REGULAR))
    pdf.add_font(_FONT_FAMILY, style="B", fname=str(_FONT_BOLD))
    pdf.add_page()
    pdf.set_margins(left=15, top=15, right=15)
    width = pdf.epw

    for turn in turns:
        role = str(turn.get("role", "")).strip() or "unknown"
        content = str(turn.get("content", ""))
        pdf.set_x(pdf.l_margin)
        pdf.set_font(_FONT_FAMILY, style="B", size=12)
        pdf.multi_cell(width, 8, role)
        pdf.set_x(pdf.l_margin)
        pdf.set_font(_FONT_FAMILY, style="", size=12)
        pdf.multi_cell(width, 8, content)
        pdf.ln(4)

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()
