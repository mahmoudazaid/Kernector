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
                f"## {index}. {case.title}",
                "",
                "### Steps",
                "",
            ]
        )
        if result.output_style == "gherkin":
            for step in case.steps:
                lines.append(f"- {step}")
        else:
            for step_index, step in enumerate(case.steps, start=1):
                lines.append(f"{step_index}. {step}")
        lines.extend(
            [
                "",
                "### Expected result",
                "",
                case.expected,
                "",
                "### References",
                "",
            ]
        )
        for ref in case.references:
            lines.append(f"- `{ref.source_id}` ({ref.source_type})")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
