"""Composition wiring for conversation transcript PDF export."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from infrastructure.export.conversation_transcript_pdf import (
    build_conversation_transcript_pdf,
)


def build_conversation_pdf(turns: Sequence[Mapping[str, Any]]) -> bytes:
    """Build PDF bytes for sanitized conversation turns."""
    return build_conversation_transcript_pdf(turns)
