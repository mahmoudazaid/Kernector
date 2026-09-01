"""Deterministic Markdown export for Software Delivery test cases."""

from __future__ import annotations

import re

from packs.software_delivery.contracts import TestGenerationResult

_FENCE_ONLY = re.compile(r"^(`{3,})$")


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
                f"## {index}. {_inline_code(case.title)}",
                "",
                "### Steps",
                "",
            ]
        )
        if result.output_style == "gherkin":
            for step in case.steps:
                lines.append(f"- {_inline_code(step)}")
        else:
            for step_index, step in enumerate(case.steps, start=1):
                lines.append(f"{step_index}. {_inline_code(step)}")
        lines.extend(
            [
                "",
                "### Expected result",
                "",
            ]
        )
        lines.extend(_contained_block(case.expected))
        lines.extend(
            [
                "",
                "### References",
                "",
            ]
        )
        for ref in case.references:
            lines.append(
                f"- {_inline_code(ref.source_id)} ({_inline_code(ref.source_type)})"
            )
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def structural_reference_headings(markdown: str) -> list[str]:
    """Return structural ``### References`` headings outside fenced field blocks."""
    headings: list[str] = []
    in_fence = False
    fence = ""
    for line in markdown.splitlines():
        fence_match = _FENCE_ONLY.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if in_fence and marker == fence:
                in_fence = False
                fence = ""
            elif not in_fence:
                in_fence = True
                fence = marker
            continue
        if not in_fence and line == "### References":
            headings.append(line)
    return headings


def _inline_text(text: str) -> str:
    """Normalize user content to one line for inline-code containment."""
    return " ".join(text.split())


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


def _contained_block(text: str) -> list[str]:
    """Wrap arbitrary multiline content in an adaptive fenced code block."""
    fence = _adaptive_fence(text)
    return [fence, *text.splitlines(), fence]


def _inline_code(text: str) -> str:
    """Contain arbitrary inline content in an adaptive Markdown code span."""
    safe = _inline_text(text)
    tick_run = _longest_backtick_run(safe)
    if tick_run == 0:
        return f"`{safe}`"
    delimiter = "`" * (tick_run + 1)
    if safe.startswith("`") or safe.endswith("`"):
        return f"{delimiter} {safe} {delimiter}"
    return f"{delimiter}{safe}{delimiter}"
