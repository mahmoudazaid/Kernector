"""Deterministic Markdown export for Software Delivery test cases."""

from __future__ import annotations

from packs.software_delivery.contracts import TestGenerationResult


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


def _safe_multiline(text: str) -> list[str]:
    """Render body text without breaking adjacent Markdown sections."""
    if not text:
        return [""]
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
    """Escape text for a Markdown inline code span."""
    safe = _single_line(text)
    if "`" in safe:
        return f"``{safe}``"
    return f"`{safe}`"
