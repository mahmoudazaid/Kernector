"""Caller-supplied test file arguments shared by the test file tools (#396, #397).

Validates the ``files`` list, enforces the size and scenario budgets, and
parses each file. Nothing is read from disk.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from domain.errors import ToolArgumentValidationError
from packs.software_delivery.errors import TestFileErrorReason as Reason
from packs.software_delivery.errors import TestFileValidationError
from packs.software_delivery.limits import (
    MAX_TEST_FILE_BYTES,
    MAX_TEST_FILE_PATH_CHARS,
    MAX_TEST_FILE_SCENARIOS,
    MAX_TEST_FILES,
    MAX_TEST_FILES_TOTAL_BYTES,
)
from packs.software_delivery.test_files.models import ParsedTestFile, TestFileTagConfig
from packs.software_delivery.test_files.parser import (
    is_supported_test_file,
    parse_test_file,
)

_FILE_KEYS = frozenset({"path", "content"})


def read_files(
    files: object, error: type[ToolArgumentValidationError]
) -> list[tuple[str, str]]:
    """Return ``(path, content)`` pairs; paths are stripped.

    Raises:
        ToolArgumentValidationError: ``error`` for a malformed list or item.
        TestFileValidationError: Too many files, an unsupported extension, a
            size budget exceeded, or a repeated path.
    """
    if not isinstance(files, Sequence) or isinstance(files, str) or not files:
        raise error("files must be a non-empty list")
    if len(files) > MAX_TEST_FILES:
        raise TestFileValidationError(None, None, Reason.TOO_MANY_FILES)
    items = [_file_item(item, error) for item in files]
    _check_sizes(items)
    return items


def parse_files(files: Sequence[tuple[str, str]], tags: TestFileTagConfig) -> list[ParsedTestFile]:
    """Parse every file within the shared ``MAX_TEST_FILE_SCENARIOS`` budget."""
    remaining = MAX_TEST_FILE_SCENARIOS
    parsed: list[ParsedTestFile] = []
    for path, content in files:
        result = parse_test_file(path, content, tags, max_scenarios=remaining)
        remaining -= len(result.scenarios)
        parsed.append(result)
    return parsed


def reject_duplicate_paths(files: Sequence[tuple[str, str]]) -> None:
    """Raise when the same path is sent twice; it would merge two scenario identities."""
    seen: set[str] = set()
    for path, _content in files:
        if path in seen:
            raise TestFileValidationError(path, None, Reason.DUPLICATE_FILE_PATH)
        seen.add(path)


def _file_item(
    item: object, error: type[ToolArgumentValidationError]
) -> tuple[str, str]:
    if not isinstance(item, Mapping) or set(item) != _FILE_KEYS:
        raise error("each file must have only path and content")
    path, content = item["path"], item["content"]
    if not isinstance(path, str) or not path.strip():
        raise error("path must be a non-empty string")
    if len(path) > MAX_TEST_FILE_PATH_CHARS:
        raise error(f"path must be at most {MAX_TEST_FILE_PATH_CHARS} characters")
    if any(not char.isprintable() for char in path):
        raise error("path must not contain control characters")
    if not isinstance(content, str) or not content.strip():
        raise error("content must be non-blank text")
    return path.strip(), content


def _check_sizes(files: list[tuple[str, str]]) -> None:
    total = 0
    for path, content in files:
        if not is_supported_test_file(path):
            raise TestFileValidationError(path, None, Reason.UNSUPPORTED_EXTENSION)
        size = len(content.encode("utf-8"))
        if size > MAX_TEST_FILE_BYTES:
            raise TestFileValidationError(path, None, Reason.FILE_TOO_LARGE)
        total += size
    if total > MAX_TEST_FILES_TOTAL_BYTES:
        raise TestFileValidationError(None, None, Reason.TOTAL_TOO_LARGE)
