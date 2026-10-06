"""Named pack-local budgets for Software Delivery Google Drive export."""

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
