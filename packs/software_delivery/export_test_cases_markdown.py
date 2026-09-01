"""Deterministic Markdown export for Software Delivery test cases."""

from __future__ import annotations

import re

from packs.software_delivery.contracts import TestGenerationResult

_FENCE_LINE = re.compile(r"^\s*`{3,}")


def export_test_cases_markdown(result: TestGenerationResult) -> str:
    """Render generated test cases and citations as Markdown text."""
    lines: list[str] = [
        "# Test Cases",
        "",
        f"**Output style:** {result.output_style}",
        "",
    ]
    for index, case in enumerate(result.test_cases, start=1):
        lines.extend(
            [
                f"## {index}. {_single_line(case.title)}",
                "",
                "### Steps",
                "",
            ]
        )
        if result.output_style == "gherkin":
            for step in case.steps:
                lines.append(f"- {_single_line(step)}")
        else:
            for step_index, step in enumerate(case.steps, start=1):
                lines.append(f"{step_index}. {_single_line(step)}")
        lines.extend(
            [
                "",
                "### Expected result",
                "",
            ]
        )
        lines.extend(_safe_multiline(case.expected))
        lines.extend(
            [
                "",
                "### References",
                "",
            ]
        )
        for ref in case.references:
            lines.append(
                f"- {_inline_code(ref.source_id)} ({_single_line(ref.source_type)})"
            )
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _single_line(text: str) -> str:
    """Collapse whitespace and escape heading markers in inline fields."""
    return " ".join(text.split()).replace("#", "\\#")


def _longest_backtick_run(text: str) -> int:
    longest = 0
    current = 0
    for char in text:
        if char == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _adaptive_fence(text: str) -> str:
    return "`" * max(3, _longest_backtick_run(text) + 1)


def _needs_fenced_block(text: str) -> bool:
    if "```" in text:
        return True
    return any(_FENCE_LINE.match(line) for line in text.splitlines())


def _safe_multiline(text: str) -> list[str]:
    """Render body text without breaking adjacent Markdown sections."""
    if not text:
        return [""]
    if _needs_fenced_block(text):
        fence = _adaptive_fence(text)
        return [fence, *text.splitlines(), fence]
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        prefix = line[: len(line) - len(stripped)]
        if stripped.startswith("#"):
            lines.append(f"{prefix}\\#{stripped[1:]}")
        else:
            lines.append(line)
    return lines


def _inline_code(text: str) -> str:
    """Escape text for a Markdown inline code span with adaptive delimiters."""
    safe = _single_line(text)
    tick_run = _longest_backtick_run(safe)
    if tick_run == 0:
        return f"`{safe}`"
    delimiter = "`" * (tick_run + 1)
    if safe.startswith("`") or safe.endswith("`"):
        return f"{delimiter} {safe} {delimiter}"
    return f"{delimiter}{safe}{delimiter}"
