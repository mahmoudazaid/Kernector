"""Helpers for building evidence refs inside detector modules."""

from __future__ import annotations

from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import EvidenceRef, LineRange


def ref_for(
    component: str,
    file: EvidenceFile,
    *,
    start: int = 1,
    end: int | None = None,
) -> EvidenceRef:
    """Cite ``file`` with a 1-based inclusive line range."""
    lines = file.content.splitlines()
    last = len(lines) if lines else 1
    return EvidenceRef(
        component=component,
        path=file.path,
        content_hash=file.content_hash,
        line_range=LineRange(start, end if end is not None else last),
    )
