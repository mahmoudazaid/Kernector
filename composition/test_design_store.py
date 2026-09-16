"""Composition bridge: pack draft Protocol over generic versioned store."""

from __future__ import annotations

from infrastructure.workspace_store.sql_store import VersionedWorkspaceStore
from packs.software_delivery.test_design.codec import (
    decode_draft_payload,
    encode_draft_payload,
)
from packs.software_delivery.test_design.models import TestCoverageDraft

TEST_DESIGN_NAMESPACE = "software-delivery:test-design"


class VersionedTestCoverageDraftRepository:
    """Adapt ``VersionedWorkspaceStore`` to the pack draft repository Protocol.

    Owns the fixed namespace constant. Contains no SQL.
    """

    def __init__(self, store: VersionedWorkspaceStore) -> None:
        self._store = store

    def create(self, draft: TestCoverageDraft) -> TestCoverageDraft:
        record = self._store.create(
            TEST_DESIGN_NAMESPACE,
            draft.draft_id,
            encode_draft_payload(draft),
        )
        return decode_draft_payload(
            record.payload,
            draft_id=record.record_id,
            version=record.version,
        )

    def get(self, draft_id: str) -> TestCoverageDraft | None:
        record = self._store.get(TEST_DESIGN_NAMESPACE, draft_id)
        if record is None:
            return None
        return decode_draft_payload(
            record.payload,
            draft_id=record.record_id,
            version=record.version,
        )

    def find_by_conversation_id(self, conversation_id: str) -> TestCoverageDraft | None:
        """Return the newest draft whose payload matches ``conversation_id``."""
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ValueError("conversation_id must be a non-empty string")
        conversation_id = conversation_id.strip()
        match: TestCoverageDraft | None = None
        for record in self._store.list_namespace(TEST_DESIGN_NAMESPACE):
            draft = decode_draft_payload(
                record.payload,
                draft_id=record.record_id,
                version=record.version,
            )
            if draft.conversation_id != conversation_id:
                continue
            if match is None or draft.version > match.version:
                match = draft
        return match

    def update(
        self,
        draft: TestCoverageDraft,
        *,
        expected_version: int,
    ) -> TestCoverageDraft:
        record = self._store.update(
            TEST_DESIGN_NAMESPACE,
            draft.draft_id,
            encode_draft_payload(draft),
            expected_version=expected_version,
        )
        return decode_draft_payload(
            record.payload,
            draft_id=record.record_id,
            version=record.version,
        )
