"""Server-side prepared call for agent Google Drive export (#309).

Builds ``software_delivery.export_test_cases_google_drive`` arguments from the
Test Design draft and a persisted export destination. Never accepts LLM- or
browser-supplied folder ids or titles for the agent path.

When no destination is saved, defaults to My Drive Home (``root``) so the
agent can interrupt for HITL without a destination-required gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

DEFAULT_DRIVE_FOLDER_ID = "root"
DEFAULT_DRIVE_DESTINATION_LABEL = "Home"
# Composition-local constant — avoid importing the pack at module load.
TOOL_NAME = "software_delivery.export_test_cases_google_drive"


class _DraftLike(Protocol):
    ticket_identifier: str
    candidates: object


class _DraftRepository(Protocol):
    def find_by_conversation_id(self, conversation_id: str) -> _DraftLike | None:
        """Return the draft for ``conversation_id``, or ``None``."""


class _DestinationLike(Protocol):
    folder_id: str
    display_label: str


class _DestinationRepository(Protocol):
    def get(self, conversation_id: str) -> _DestinationLike | None:
        """Return the persisted destination for ``conversation_id``, or ``None``."""


@dataclass(frozen=True, slots=True)
class ExportDestinationRequired:
    """Legacy typed gate; prepare no longer returns this (Home is the default)."""

    outcome: str = "export_destination_required"


@dataclass(frozen=True, slots=True)
class DraftUnavailable:
    """No draft, or no selected titles, for the trusted conversation."""


@dataclass(frozen=True, slots=True)
class PreparedDriveExportCall:
    """Closed-over Drive Tool invocation ready for the agent BoundTool."""

    tool_name: str
    arguments: Mapping[str, object]
    destination_label: str
    selected_title_count: int
    file_name: str | None = None


def prepare_drive_export_call(
    *,
    conversation_id: str,
    drafts: _DraftRepository,
    destinations: _DestinationRepository,
) -> PreparedDriveExportCall | DraftUnavailable:
    """Resolve Drive Tool args from draft + destination (Home when unset).

    Args:
        conversation_id: Trusted conversation id (never from tool arguments).
        drafts: Lookup for the Test Design draft tied to the conversation.
        destinations: Lookup for the persisted export destination.

    Returns:
        PreparedDriveExportCall when the draft has selected titles (destination
        defaults to Home / ``root`` when none is saved); DraftUnavailable when
        the draft or selection is missing.
    """
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise ValueError("conversation_id must be a non-empty string")
    conversation_id = conversation_id.strip()

    draft = drafts.find_by_conversation_id(conversation_id)
    if draft is None:
        return DraftUnavailable()

    titles = tuple(
        candidate.title.strip()
        for candidate in draft.candidates  # type: ignore[attr-defined]
        if getattr(candidate, "selected", False)
        and isinstance(getattr(candidate, "title", None), str)
        and candidate.title.strip()
    )
    if not titles:
        return DraftUnavailable()

    destination = destinations.get(conversation_id)
    folder_id = (
        destination.folder_id if destination is not None else DEFAULT_DRIVE_FOLDER_ID
    )
    destination_label = (
        destination.display_label
        if destination is not None
        else DEFAULT_DRIVE_DESTINATION_LABEL
    )
    from packs.software_delivery.tools.export_test_cases_google_drive import (
        default_export_file_name,
    )

    file_name = default_export_file_name(draft.ticket_identifier)

    arguments: dict[str, object] = {
        "document_title": draft.ticket_identifier,
        "titles": list(titles),
        "folder_id": folder_id,
        "file_name": file_name,
    }
    return PreparedDriveExportCall(
        tool_name=TOOL_NAME,
        arguments=MappingProxyType(arguments),
        destination_label=destination_label,
        selected_title_count=len(titles),
        file_name=file_name,
    )
