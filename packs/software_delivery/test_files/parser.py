"""Entry point: dispatch ``.robot`` / ``.feature`` content to its parser (#396)."""

from __future__ import annotations

from packs.software_delivery.errors import TestFileErrorReason, TestFileValidationError
from packs.software_delivery.test_files.gherkin import parse_gherkin
from packs.software_delivery.test_files.models import ParsedTestFile, TestFileTagConfig
from packs.software_delivery.test_files.robot import parse_robot

ROBOT_EXTENSION = ".robot"
GHERKIN_EXTENSION = ".feature"
_BOM = "\ufeff"


def parse_test_file(
    path: str,
    text: str,
    tags: TestFileTagConfig,
    *,
    max_scenarios: int | None = None,
) -> ParsedTestFile:
    """Parse caller-supplied file text; never reads the disk or calls Jira/Xray.

    Args:
        path: Caller's path for the file; selects the syntax by extension.
        text: Full file content.
        tags: Configured tag names.
        max_scenarios: Remaining scenario budget; ``None`` means unbounded.

    Raises:
        TestFileValidationError: Unsupported extension, malformed or unsupported
            syntax, conflicting key tags, or the budget exceeded; names the
            file and line.
    """
    if not is_supported_test_file(path):
        raise TestFileValidationError(path, None, TestFileErrorReason.UNSUPPORTED_EXTENSION)
    parse = parse_gherkin if path.lower().endswith(GHERKIN_EXTENSION) else parse_robot
    return parse(path, text.removeprefix(_BOM), tags, max_scenarios)


def is_supported_test_file(path: str) -> bool:
    return path.lower().endswith((ROBOT_EXTENSION, GHERKIN_EXTENSION))
