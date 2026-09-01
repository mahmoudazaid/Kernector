"""Named pack-local budgets for Software Delivery test-case generation."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

# Per-field (aligned with default MAX_INPUT_LENGTH for text fields)
MAX_TARGET_CHARS = 10_000
MAX_EVIDENCE_TEXT_CHARS = 10_000
MAX_SOURCE_ID_CHARS = 256
MAX_SOURCE_TYPE_CHARS = 64
MAX_EVIDENCE_ITEMS = 32
MAX_GENERATED_CASES = 25
MAX_STEPS_PER_CASE = 20
MAX_TITLE_CHARS = 200
MAX_STEP_CHARS = 500
MAX_EXPECTED_CHARS = 1_000
MAX_EVIDENCE_IDS_PER_CASE = MAX_EVIDENCE_ITEMS

# Cumulative: entire serialized prompt / response / result JSON
MAX_TOTAL_INPUT_CHARS = 16_000
MAX_MODEL_RESPONSE_CHARS = 8_192
MAX_TOTAL_OUTPUT_CHARS = 8_192

TEST_GENERATION_MODEL_SETTINGS: Mapping[str, object] = MappingProxyType(
    {
        "temperature": 0,
        "max_tokens": 2048,
    }
)

MAX_REQUIREMENTS_CHARS = 10_000
MAX_ANALYSIS_ANSWER_CHARS = 4_000
MAX_ANALYSIS_FINDINGS = 25
MAX_FINDING_STATEMENT_CHARS = 1_000
MAX_EVIDENCE_IDS_PER_FINDING = MAX_EVIDENCE_ITEMS

REQUIREMENTS_ANALYSIS_MODEL_SETTINGS: Mapping[str, object] = MappingProxyType(
    {
        "temperature": 0,
        "max_tokens": 2048,
    }
)
