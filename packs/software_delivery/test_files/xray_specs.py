"""Build Xray test specs from parsed file scenarios (#397).

Manual scenarios become one Xray step per action; ``Then`` lines and the
``And`` / ``But`` lines after them are that step's expected result. Cucumber
scenarios become Gherkin steps with the ``Background`` first and, for an
outline, the ``Examples`` blocks. Data tables and doc strings stay with the
line they belong to.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from domain.test_management.xray import XrayTestSpec, XrayTestStep
from packs.software_delivery.test_files.models import (
    ExamplesBlock,
    ParsedTestFile,
    TableRow,
    TestFileScenario,
    TestStep,
)

_ASSERTION = "then"
_CONTINUATIONS = frozenset({"and", "but"})
_INDENT = "  "


@dataclass(frozen=True, slots=True)
class SpecProblem:
    """The scenario cannot become a spec; ``reason`` is a fixed result code."""

    reason: str


@dataclass(slots=True)
class _ManualStep:
    action: list[str] = field(default_factory=list)
    expected: list[str] = field(default_factory=list)


def build_spec(
    parsed: ParsedTestFile,
    scenario: TestFileScenario,
    *,
    story_key: str | None,
    component: str | None,
) -> XrayTestSpec | SpecProblem:
    """Return the spec linked to ``story_key``, or why the scenario cannot be built."""
    background = parsed.background.steps if parsed.background is not None else ()
    steps = (*background, *scenario.steps)
    if scenario.kind == "manual":
        if scenario.outline:
            return SpecProblem("manual_outline_unsupported")
        manual = _manual_steps(steps)
        if isinstance(manual, SpecProblem):
            return manual
        return XrayTestSpec(
            title=scenario.summary,
            kind="manual",
            steps=manual,
            link_issue_key=story_key,
            source_issue_key=story_key,
            component=component,
        )
    lines = [line for step in steps for line in _step_lines(step, _INDENT)]
    for examples in scenario.examples if scenario.outline else ():
        lines.extend(_examples_lines(examples))
    return XrayTestSpec(
        title=scenario.summary,
        kind="cucumber",
        gherkin="\n".join(lines),
        link_issue_key=story_key,
        source_issue_key=story_key,
        component=component,
        outline=scenario.outline,
    )


def _manual_steps(steps: Iterable[TestStep]) -> tuple[XrayTestStep, ...] | SpecProblem:
    built: list[_ManualStep] = []
    in_expected = False
    for step in steps:
        keyword = step.keyword.casefold()
        lines = _step_lines(step, "")
        if keyword == _ASSERTION:
            if not built:
                return SpecProblem("assertion_without_action")
            in_expected = True
            built[-1].expected.extend(lines)
        elif keyword in _CONTINUATIONS and built:
            (built[-1].expected if in_expected else built[-1].action).extend(lines)
        else:
            in_expected = False
            built.append(_ManualStep(action=list(lines)))
    return tuple(
        XrayTestStep(action="\n".join(step.action), expected="\n".join(step.expected))
        for step in built
    )


def _step_lines(step: TestStep, indent: str) -> list[str]:
    lines = [step.text]
    if step.data_table is not None:
        lines.extend(indent + _row(row) for row in step.data_table.rows)
    doc = step.doc_string
    if doc is not None:
        lines.append(f"{indent}{doc.delimiter}{doc.media_type}")
        lines.extend(_doc_content(line, doc.indent, indent) for line in doc.lines)
        lines.append(f"{indent}{doc.delimiter}")
    return lines


def _doc_content(line: str, column: int, indent: str) -> str:
    """Re-indent ``line`` under a delimiter at ``indent``, as Gherkin strips up to ``column``."""
    content = line[min(column, len(line) - len(line.lstrip())) :]
    return f"{indent}{content}" if content else ""


def _examples_lines(examples: ExamplesBlock) -> list[str]:
    lines = [""]
    if examples.tags:
        lines.append(" ".join(f"@{tag}" for tag in examples.tags))
    title = f"{examples.keyword}: {examples.name}" if examples.name else f"{examples.keyword}:"
    lines.append(title)
    lines.extend(_INDENT + _row(row) for row in (examples.header, *examples.rows))
    return lines


def _row(row: TableRow) -> str:
    return "| " + " | ".join(row.cells) + " |"
