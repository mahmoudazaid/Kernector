"""Documented well-known artifact kind tokens (ADR 0011, #373).

Not a closed validation set for ``ArtifactDescriptor.kind`` — extractors and
packs may introduce other opaque tokens — but the members below are the stable
vocabulary used by Software Delivery defaults and acceptance fixtures.
"""

from __future__ import annotations

from enum import StrEnum


class ArtifactKind(StrEnum):
    """Well-known artifact kinds; validation accepts any opaque token shape."""

    STORY = "story"
    BUG = "bug"
    TEST_CASE = "test_case"
    CODE_FILE = "code_file"
    AUTOMATED_TEST = "automated_test"
    TEST_SUPPORT = "test_support"
    DOCUMENT = "document"
    WORK_ITEM = "work_item"
    API_SPEC = "api_spec"
    API_OPERATION = "api_operation"
