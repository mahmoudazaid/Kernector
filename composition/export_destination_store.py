"""Persisted Google Drive export destination per conversation (#309)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from infrastructure.workspace_store.errors import (
    VersionedStoreConflictError,
    VersionedStoreNotFoundError,
)
from infrastructure.workspace_store.sql_store import VersionedWorkspaceStore

EXPORT_DESTINATION_NAMESPACE = "software-delivery:export-destination"


@dataclass(frozen=True, slots=True)
class ExportDestination:
    """Server-side export destination; folder id never goes to chat projections."""

    folder_id: str
    display_label: str
    version: int = 1


class VersionedExportDestinationRepository:
    """Adapt ``VersionedWorkspaceStore`` for per-conversation destinations.

    ``record_id`` is the trusted ``conversation_id``.
    """

    def __init__(self, store: VersionedWorkspaceStore) -> None:
        self._store = store

    def get(self, conversation_id: str) -> ExportDestination | None:
        record = self._store.get(EXPORT_DESTINATION_NAMESPACE, conversation_id.strip())
        if record is None:
            return None
        return _decode(record.payload, version=record.version)

    def upsert(
        self,
        conversation_id: str,
        *,
        folder_id: str,
        display_label: str,
    ) -> ExportDestination:
        """Create or replace the destination for ``conversation_id``."""
        conversation_id = conversation_id.strip()
        folder_id = folder_id.strip()
        display_label = display_label.strip()
        if not conversation_id:
            raise ValueError("conversation_id must be a non-empty string")
        if not folder_id:
            raise ValueError("folder_id must be a non-empty string")
        if not display_label:
            raise ValueError("display_label must be a non-empty string")
        payload = json.dumps(
            {"folder_id": folder_id, "display_label": display_label},
            separators=(",", ":"),
            sort_keys=True,
        )
        existing = self._store.get(EXPORT_DESTINATION_NAMESPACE, conversation_id)
        if existing is None:
            try:
                record = self._store.create(
                    EXPORT_DESTINATION_NAMESPACE, conversation_id, payload
                )
            except VersionedStoreConflictError:
                existing = self._store.get(EXPORT_DESTINATION_NAMESPACE, conversation_id)
                if existing is None:
                    raise
                record = self._store.update(
                    EXPORT_DESTINATION_NAMESPACE,
                    conversation_id,
                    payload,
                    expected_version=existing.version,
                )
            return _decode(record.payload, version=record.version)
        try:
            record = self._store.update(
                EXPORT_DESTINATION_NAMESPACE,
                conversation_id,
                payload,
                expected_version=existing.version,
            )
        except VersionedStoreNotFoundError:
            record = self._store.create(
                EXPORT_DESTINATION_NAMESPACE, conversation_id, payload
            )
        return _decode(record.payload, version=record.version)


def _decode(payload: str, *, version: int) -> ExportDestination:
    raw = json.loads(payload)
    if not isinstance(raw, dict):
        raise ValueError("export destination payload must be an object")
    folder_id = raw.get("folder_id")
    display_label = raw.get("display_label")
    if not isinstance(folder_id, str) or not folder_id.strip():
        raise ValueError("folder_id must be a non-empty string")
    if not isinstance(display_label, str) or not display_label.strip():
        raise ValueError("display_label must be a non-empty string")
    return ExportDestination(
        folder_id=folder_id.strip(),
        display_label=display_label.strip(),
        version=version,
    )
