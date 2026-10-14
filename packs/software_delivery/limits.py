"""Named pack-local budgets for Software Delivery tools."""

from __future__ import annotations

# Google Drive export (#197): titles plus optional structured cases
MAX_EXPORT_DOCUMENT_TITLE_CHARS = 200
MAX_EXPORT_TITLES = 50
MAX_EXPORT_TITLE_CHARS = 200
MAX_EXPORT_CASE_ITEMS = 40
MAX_EXPORT_CASE_ITEM_CHARS = 2_000
MAX_EXPORT_GHERKIN_CHARS = 8_000
MAX_EXPORT_FILE_NAME_CHARS = 128
MAX_EXPORT_ARTIFACT_BYTES = 1_048_576
DEFAULT_EXPORT_FILE_NAME = "test-cases.md"

# Test file scenario preview (#396): caller-supplied .robot / .feature content
MAX_TEST_FILES = 20
MAX_TEST_FILE_PATH_CHARS = 512
MAX_TEST_FILE_BYTES = 262_144
MAX_TEST_FILES_TOTAL_BYTES = 1_048_576
MAX_TEST_FILE_SCENARIOS = 500

# Xray key write-back (#399): full rewritten content plus diffs in one result;
# over the cap the call is rejected, never truncated.
MAX_XRAY_KEY_WRITEBACK_RESULT_BYTES = 2 * MAX_TEST_FILES_TOTAL_BYTES

# Pull Xray tests into files (#400): remote keys considered and full JSON result.
MAX_PULL_XRAY_TESTS = 200
MAX_PULL_XRAY_RESULT_BYTES = 2 * MAX_XRAY_KEY_WRITEBACK_RESULT_BYTES
