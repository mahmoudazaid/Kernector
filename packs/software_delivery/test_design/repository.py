"""Pack-local repository Protocol for test-design drafts."""

from __future__ import annotations

from typing import Protocol

from packs.software_delivery.test_design.models import TestCoverageDraft


class TestCoverageDraftRepository(Protocol):
    """Persist and load typed test-coverage drafts for one workspace."""

    def create(self, draft: TestCoverageDraft) -> TestCoverageDraft:
        """Insert a new draft. Existing ids fail."""
        ...

    def get(self, draft_id: str) -> TestCoverageDraft | None:
        """Return the draft for ``draft_id``, or ``None`` when absent."""
        ...

    def update(
        self,
        draft: TestCoverageDraft,
        *,
        expected_version: int,
    ) -> TestCoverageDraft:
        """Compare-and-swap update; returns draft with incremented version."""
        ...
