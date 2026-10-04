"""Canonical client-supplied Issue evidence and the shared evidence fingerprint.

Client-supplied drafts (#355) are rendered once, at start, by
:func:`render_client_evidence`; the result is persisted and hashed by
:func:`evidence_fingerprint`. Confirm and generate never re-render, so the
fingerprint cannot drift between start, confirm and generate.
"""

from __future__ import annotations

import hashlib

from domain.knowledge import SourceReference
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.limits import MAX_EVIDENCE_TEXT_CHARS

CLIENT_SUPPLIED_SOURCE_TYPE = "client_supplied"
CLIENT_SOURCE_PROVIDER = "client"
CLIENT_EVIDENCE_LIMIT_GUIDANCE = (
    "Title, body, acceptance_criteria and source_url together must fit in "
    f"{MAX_EVIDENCE_TEXT_CHARS:,} characters; shorten the body first and keep "
    "the acceptance criteria."
)


def client_source_reference(ticket_identifier: str) -> SourceReference:
    """Return the evidence reference for a client-supplied ticket."""
    return SourceReference(
        f"client:{_normalize(ticket_identifier)}", CLIENT_SUPPLIED_SOURCE_TYPE
    )


def render_client_evidence(
    *,
    ticket_identifier: str,
    title: str,
    body: str,
    acceptance_criteria: str | None = None,
    source_url: str | None = None,
) -> str:
    """Render supplied Issue fields into the one canonical evidence text.

    Each field has ``\\r\\n`` and ``\\r`` converted to ``\\n`` and is stripped.
    Lines join with ``\\n`` and there is no trailing newline. The ``Source:``
    line and the acceptance criteria block are omitted when absent or blank.
    The rendered text is never truncated, so no supplied field is silently
    dropped before it reaches the model.

    Raises:
        TestDesignValidationError: ``ticket_identifier``, ``title`` or
            ``body`` is blank, or the rendered text exceeds
            ``MAX_EVIDENCE_TEXT_CHARS``.
    """
    ticket = _require(ticket_identifier, "ticket_identifier")
    heading = _require(title, "title")
    description = _require(body, "body")
    url = _normalize(source_url or "")
    criteria = _normalize(acceptance_criteria or "")
    lines = [f"# {heading}", "", f"Ticket: {ticket}"]
    if url:
        lines.append(f"Source: {url}")
    lines.extend(["", "## Description", "", description])
    if criteria:
        lines.extend(["", "## Acceptance criteria", "", criteria])
    rendered = "\n".join(lines)
    if len(rendered) > MAX_EVIDENCE_TEXT_CHARS:
        raise TestDesignValidationError(
            "supplied issue content must fit in "
            f"{MAX_EVIDENCE_TEXT_CHARS} characters, got {len(rendered)}"
        )
    return rendered


def evidence_fingerprint(reference: SourceReference, budgeted: str) -> str:
    """Return the SHA-256 fingerprint of budgeted evidence for *reference*."""
    return hashlib.sha256(
        f"{reference.source_type}\0{reference.source_id}\0{budgeted}".encode("utf-8")
    ).hexdigest()


def _normalize(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _require(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _normalize(value):
        raise TestDesignValidationError(f"{field_name} must be non-empty")
    return _normalize(value)
