"""Entry point: dispatch ``.robot`` / ``.feature`` content to its parser (#396)."""

from __future__ import annotations

from packs.software_delivery.errors import TestFileErrorReason, TestFileValidationError
from packs.software_delivery.test_files.gherkin import parse_gherkin_layout
from packs.software_delivery.test_files.layout import FileLayout
from packs.software_delivery.test_files.models import ParsedTestFile, TestFileTagConfig
from packs.software_delivery.test_files.robot import parse_robot_layout

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
    return parse_test_file_layout(path, text, tags, max_scenarios=max_scenarios)[0]


def parse_test_file_layout(
    path: str,
    text: str,
    tags: TestFileTagConfig,
    *,
    max_scenarios: int | None = None,
) -> tuple[ParsedTestFile, FileLayout]:
    """Like ``parse_test_file``, plus each scenario's source rows for write-back (#399).

    Raises:
        TestFileValidationError: As ``parse_test_file``.
    """
    if not is_supported_test_file(path):
        raise TestFileValidationError(path, None, TestFileErrorReason.UNSUPPORTED_EXTENSION)
    parse = (
        parse_gherkin_layout if path.lower().endswith(GHERKIN_EXTENSION) else parse_robot_layout
    )
    return parse(path, text.removeprefix(_BOM), tags, max_scenarios)


def is_supported_test_file(path: str) -> bool:
    return path.lower().endswith((ROBOT_EXTENSION, GHERKIN_EXTENSION))
