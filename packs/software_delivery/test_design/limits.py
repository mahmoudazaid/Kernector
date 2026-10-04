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
MAX_AUTOMATION_RATIONALE_CHARS = 500
MAX_PRECONDITIONS_CHARS = 2_000
MAX_PRECONDITIONS_LINES = 40
MAX_STEP_CHARS = 500
MAX_STEPS = 40
MAX_EXPECTED_RESULT_CHARS = 2_000
MAX_EXPECTED_RESULT_LINES = 40
MAX_GHERKIN_CHARS = 8_000
MAX_EVIDENCE_FINGERPRINT_CHARS = 128
MAX_GENERATE_CANDIDATES = 20
# Client evidence is rejected, never truncated. The rendered text adds 65
# characters of headings and blank lines plus the "Ticket:" value around the
# supplied fields, so the published content limit reserves that worst case and
# rendered evidence always fits MAX_EVIDENCE_TEXT_CHARS.
CLIENT_EVIDENCE_RENDER_OVERHEAD_CHARS = 65 + MAX_TICKET_IDENTIFIER_CHARS
MAX_CLIENT_CONTENT_CHARS = (
    MAX_EVIDENCE_TEXT_CHARS - CLIENT_EVIDENCE_RENDER_OVERHEAD_CHARS
)
MAX_CLIENT_BODY_CHARS = MAX_CLIENT_CONTENT_CHARS
MAX_CLIENT_ACCEPTANCE_CRITERIA_CHARS = MAX_CLIENT_CONTENT_CHARS
MAX_CLIENT_SOURCE_URL_CHARS = 2_048

PLAN_COVERAGE_MODEL_SETTINGS: Mapping[str, object] = {
    "temperature": 0,
    "max_tokens": 4096,
}

GENERATE_CASES_MODEL_SETTINGS: Mapping[str, object] = {
    "temperature": 0,
    "max_tokens": 8192,
}
