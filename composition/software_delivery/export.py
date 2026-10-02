"""Composition adapters for Software Delivery Markdown export rendering."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from application.markdown import MarkdownDocument, MarkdownSection, render_markdown

if TYPE_CHECKING:
    from packs.software_delivery.tools.export_test_cases_google_drive import (
        ExportCase,
        ExportContent,
    )


def render_export_markdown(content: ExportContent) -> str:
    """Map validated export content onto the shared #305 Markdown renderer."""
    sections: list[MarkdownSection] = (
        []
        if content.cases
        else [MarkdownSection(heading="Selected tests", bullet_items=content.titles)]
    )
    cucumber = [case for case in content.cases if case.test_type == "cucumber"]
    manual = [case for case in content.cases if case.test_type == "manual"]
    if cucumber:
        sections.append(
            MarkdownSection(
                heading="Cucumber",
                code_block=_feature_file(content, cucumber),
                code_language="gherkin",
            )
        )
    if manual:
        sections.append(MarkdownSection(heading="Manual"))
        for case in manual:
            sections.extend(_manual_sections(case))
    return render_markdown(
        MarkdownDocument(title=content.document_title, sections=tuple(sections))
    )


def _feature_file(content: ExportContent, cases: list[ExportCase]) -> str:
    return render_feature_file(
        feature=content.cucumber_feature.strip() or content.document_title.strip(),
        background=content.cucumber_background,
        scenarios=[(case.title, case.gherkin) for case in cases],
    )


def render_feature_file(
    *, feature: str, background: str, scenarios: Sequence[tuple[str, str]]
) -> str:
    """Render one Gherkin Feature with a shared Background.

    Args:
        feature: Feature title, without the ``Feature:`` keyword.
        background: Background steps; a leading ``Background:`` line is dropped.
        scenarios: ``(title, gherkin)`` pairs; each title names its Scenario and
            any ``Scenario:`` line inside the gherkin is dropped.

    Returns:
        The Feature text, without a trailing newline.
    """
    lines = [f"Feature: {feature.strip()}"]
    background_steps = _step_lines(background, _BACKGROUND_HEADERS)
    if background_steps:
        lines.extend(["", "  Background:"])
        lines.extend(_indent_step(line) for line in background_steps)
    for title, gherkin in scenarios:
        steps = _step_lines(gherkin, _SCENARIO_HEADERS)
        outline = any(line.lower().startswith(_EXAMPLES_HEADERS) for line in steps)
        keyword = "Scenario Outline" if outline else "Scenario"
        lines.extend(["", f"  {keyword}: {title.strip()}"])
        lines.extend(_indent_step(line) for line in steps)
    return "\n".join(lines)


_SCENARIO_HEADERS = ("scenario:", "scenario outline:", "scenario template:", "example:")
_BACKGROUND_HEADERS = ("background:",)
_EXAMPLES_HEADERS = ("examples:", "scenarios:")


def _step_lines(text: str, headers: tuple[str, ...]) -> list[str]:
    return [
        line
        for line in (raw.strip() for raw in text.splitlines())
        if line and not line.lower().startswith(headers)
    ]


def _indent_step(line: str) -> str:
    return f"      {line}" if line.startswith("|") else f"    {line}"


def _manual_sections(case: ExportCase) -> list[MarkdownSection]:
    sections = [MarkdownSection(heading=case.title, level=3)]
    if case.preconditions:
        sections.append(
            MarkdownSection(
                heading="Preconditions", ordered_items=case.preconditions, level=4
            )
        )
    sections.append(
        MarkdownSection(heading="Steps", ordered_items=case.steps, level=4)
    )
    sections.append(
        MarkdownSection(
            heading="Expected result", ordered_items=case.expected_result, level=4
        )
    )
    return sections


def _non_empty_lines(value: str) -> list[str]:
    return [
        line.rstrip()
        for line in value.replace("\r\n", "\n").split("\n")
        if line.strip()
    ]


def draft_export_case_arguments(draft: object) -> dict[str, object]:
    """Build the optional ``cases`` / Cucumber tool arguments from a draft.

    Only selected candidates with an available generated case are exported, in
    candidate order; tests that need more detail from the ticket stay out.
    """
    candidates = getattr(draft, "candidates", ()) or ()
    titles = {
        candidate.candidate_id: candidate.title.strip()
        for candidate in candidates
        if getattr(candidate, "selected", False) and candidate.title.strip()
    }
    cases_by_id = {
        case.candidate_id: case
        for case in getattr(draft, "generated_cases", ()) or ()
        if case.availability == "available"
    }
    cases: list[dict[str, object]] = []
    for candidate_id, title in titles.items():
        case = cases_by_id.get(candidate_id)
        if case is None:
            continue
        if case.test_type == "cucumber":
            if not case.gherkin.strip():
                continue
            cases.append(
                {"title": title, "test_type": "cucumber", "gherkin": case.gherkin}
            )
            continue
        steps = [step.strip() for step in case.steps if step.strip()]
        expected = _non_empty_lines(case.expected_result)
        if not steps or not expected:
            continue
        cases.append(
            {
                "title": title,
                "test_type": "manual",
                "preconditions": [
                    line.strip() for line in _non_empty_lines(case.preconditions)
                ],
                "steps": steps,
                "expected_result": [line.strip() for line in expected],
            }
        )
    if not cases:
        return {}
    arguments: dict[str, object] = {"cases": cases}
    if any(item["test_type"] == "cucumber" for item in cases):
        arguments["cucumber_feature"] = getattr(draft, "cucumber_feature", "") or ""
        arguments["cucumber_background"] = (
            getattr(draft, "cucumber_background", "") or ""
        )
    return arguments
