"""Pure projection of Software Delivery test cases into export formats."""

from __future__ import annotations

import csv
import io
import json

from composition import TestCasesView


def cases_to_json(
    markdown: str,
    test_cases: TestCasesView | None = None,
) -> str:
    """Serialize generated cases as JSON; fall back to markdown wrapper."""
    if test_cases is None:
        return json.dumps({"markdown": markdown}, ensure_ascii=False, indent=2)
    payload = {
        "output_style": test_cases.output_style,
        "cases": [
            {
                "title": case.title,
                "steps": list(case.steps),
                "expected": case.expected,
                "references": [
                    {
                        "source_id": ref.source_id,
                        "source_type": ref.source_type,
                    }
                    for ref in case.references
                ],
            }
            for case in test_cases.cases
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def cases_to_csv(
    markdown: str,
    test_cases: TestCasesView | None = None,
) -> str:
    """Serialize cases as CSV columns; fall back to a single markdown row."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if test_cases is None:
        writer.writerow(["markdown"])
        writer.writerow([markdown])
        return buffer.getvalue()

    writer.writerow(["title", "steps", "expected", "references"])
    for case in test_cases.cases:
        refs = "; ".join(
            f"{ref.source_id} ({ref.source_type})" for ref in case.references
        )
        writer.writerow(
            [
                case.title,
                " | ".join(case.steps),
                case.expected,
                refs,
            ]
        )
    return buffer.getvalue()


def cases_pdf_turns(
    markdown: str,
    test_cases: TestCasesView | None = None,
) -> tuple[dict[str, str], ...]:
    """Build PDF section turns from structured cases or markdown body."""
    if test_cases is None:
        return ({"role": "Test cases", "content": markdown},)

    turns: list[dict[str, str]] = []
    for index, case in enumerate(test_cases.cases, start=1):
        steps = "\n".join(
            f"{step_index}. {step}"
            for step_index, step in enumerate(case.steps, start=1)
        )
        refs = ", ".join(
            f"{ref.source_id} ({ref.source_type})" for ref in case.references
        )
        body = f"{steps}\n\nExpected: {case.expected}\nReferences: {refs}"
        turns.append({"role": f"{index}. {case.title}", "content": body})
    if not turns and markdown.strip():
        return ({"role": "Test cases", "content": markdown},)
    return tuple(turns)
