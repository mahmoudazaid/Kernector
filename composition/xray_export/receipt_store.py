"""Persisted Xray creation receipts per Test Design draft.

Kept beside the draft, not inside it, so draft edits and regeneration never
drop the record. Only issue keys, the project key and a timestamp are stored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from infrastructure.workspace_store.errors import (
    VersionedStoreConflictError,
    VersionedStoreVersionConflictError,
)
from infrastructure.workspace_store.sql_store import VersionedWorkspaceStore

XRAY_RECEIPT_NAMESPACE = "software-delivery:xray-receipt"
_MAX_KEYS = 500


@dataclass(frozen=True, slots=True)
class XrayExportRecord:
    """All Xray tests created so far from one draft."""

    project_key: str
    created_keys: tuple[str, ...]
    last_created_at: str


class VersionedXrayReceiptRepository:
    """Adapt ``VersionedWorkspaceStore``; ``record_id`` is the draft id."""

    def __init__(self, store: VersionedWorkspaceStore) -> None:
        self._store = store

    def get(self, draft_id: str) -> XrayExportRecord | None:
        record = self._store.get(XRAY_RECEIPT_NAMESPACE, draft_id)
        return None if record is None else _decode(record.payload)

    def append(
        self, draft_id: str, *, project_key: str, created_keys: tuple[str, ...]
    ) -> XrayExportRecord:
        """Add ``created_keys`` to the draft's record, creating it if needed."""
        now = datetime.now(UTC).isoformat()
        for _ in range(3):
            existing = self._store.get(XRAY_RECEIPT_NAMESPACE, draft_id)
            previous = () if existing is None else _decode(existing.payload).created_keys
            merged = XrayExportRecord(
                project_key=project_key,
                created_keys=tuple(dict.fromkeys((*previous, *created_keys)))[-_MAX_KEYS:],
                last_created_at=now,
            )
            payload = _encode(merged)
            try:
                if existing is None:
                    self._store.create(XRAY_RECEIPT_NAMESPACE, draft_id, payload)
                else:
                    self._store.update(
                        XRAY_RECEIPT_NAMESPACE,
                        draft_id,
                        payload,
                        expected_version=existing.version,
                    )
            except (VersionedStoreConflictError, VersionedStoreVersionConflictError):
                continue
            return merged
        raise VersionedStoreConflictError("xray receipt changed concurrently")


def _encode(record: XrayExportRecord) -> str:
    return json.dumps(
        {
            "project_key": record.project_key,
            "created_keys": list(record.created_keys),
            "last_created_at": record.last_created_at,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode(payload: str) -> XrayExportRecord:
    raw = json.loads(payload)
    if not isinstance(raw, dict):
        raise ValueError("xray receipt payload must be an object")
    keys = raw.get("created_keys")
    return XrayExportRecord(
        project_key=str(raw.get("project_key", "")),
        created_keys=tuple(k for k in keys if isinstance(k, str))
        if isinstance(keys, list)
        else (),
        last_created_at=str(raw.get("last_created_at", "")),
    )
