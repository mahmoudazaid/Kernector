"""Pack-local contracts shared by Software Delivery chat intent selection."""

from __future__ import annotations

from typing import Literal

TestCaseStyle = Literal["steps", "gherkin"]
TEST_CASE_STYLES: frozenset[str] = frozenset({"steps", "gherkin"})
TEST_CASE_STYLES_DISPLAY = str(sorted(TEST_CASE_STYLES))
