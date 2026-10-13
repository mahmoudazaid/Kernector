"""Approval prompt titles for file scenarios (#397, #398); never step text."""

from __future__ import annotations

from collections.abc import Sequence

from packs.software_delivery.test_files.models import ParsedTestFile, TestFileScenario

MAX_APPROVAL_TITLES = 10
MAX_APPROVAL_TITLE_CHARS = 120


def scenario_titles(
    scenarios: Sequence[tuple[ParsedTestFile, TestFileScenario]],
) -> tuple[str, ...]:
    """``file:line · summary`` for the first scenarios, then ``+N more``."""
    titles = [
        _shorten(f"{parsed.path.rsplit('/', 1)[-1]}:{scenario.line} · {scenario.summary}")
        for parsed, scenario in scenarios[:MAX_APPROVAL_TITLES]
    ]
    if len(scenarios) > MAX_APPROVAL_TITLES:
        titles.append(f"+{len(scenarios) - MAX_APPROVAL_TITLES} more")
    return tuple(titles)


def _shorten(text: str) -> str:
    if len(text) <= MAX_APPROVAL_TITLE_CHARS:
        return text
    return text[: MAX_APPROVAL_TITLE_CHARS - 1] + "…"
