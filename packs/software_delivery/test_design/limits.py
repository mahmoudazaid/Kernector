"""Named pack-local budgets for the test-design workflow."""

from __future__ import annotations

from collections.abc import Mapping

MAX_TICKET_IDENTIFIER_CHARS = 160
MAX_CANDIDATES = 40
MAX_SUGGESTED_CANDIDATES = 12
MAX_TITLE_CHARS = 200
MAX_RATIONALE_CHARS = 1_000
MAX_EVIDENCE_REFS = 16
MAX_EVIDENCE_TEXT_CHARS = 10_000
MAX_ID_CHARS = 128

PLAN_COVERAGE_MODEL_SETTINGS: Mapping[str, object] = {
    "temperature": 0,
    "max_tokens": 4096,
}
