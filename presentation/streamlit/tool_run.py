"""Pure formatters for tool-run presentation.

No execution, retrieval, or orchestration — only Markdown lines derived from
typed composition views supplied by #170 or test fixtures.
"""

from __future__ import annotations

from collections.abc import Sequence

from composition import RiskFactorView, TestCaseView, ToolCallView
from domain.knowledge import SourceReference


def _references(references: Sequence[SourceReference]) -> str:
    return ", ".join(f"`{ref.source_id}` ({ref.source_type})" for ref in references)


def tool_call_lines(calls: Sequence[ToolCallView]) -> tuple[str, ...]:
    """Render the generic envelope: tool name, status, and authored summary."""
    lines: list[str] = []
    for call in calls:
        if call.ok:
            detail = f" — {call.summary}" if call.summary else ""
            lines.append(f"- `{call.tool_name}` — succeeded{detail}")
        else:
            lines.append(f"- `{call.tool_name}` — failed")
    return tuple(lines)


def risk_factor_bullets(
    factors: Sequence[RiskFactorView],
) -> tuple[str, ...]:
    """Render risk factors as Markdown bullets, each carrying its provenance."""
    return tuple(
        f"- `{factor.factor_id}` (weight {factor.weight}) — "
        + _references(factor.references)
        for factor in factors
    )


def case_lines(case: TestCaseView) -> tuple[str, ...]:
    """Render one generated case: numbered steps, expectation, provenance."""
    return (
        *(f"{index}. {step}" for index, step in enumerate(case.steps, start=1)),
        "",
        f"**Expected:** {case.expected}",
        f"**References:** {_references(case.references)}",
    )
