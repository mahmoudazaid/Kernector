"""Diff a scenario's spec against the existing Xray test into a sparse patch (#398).

A Manual <-> Cucumber switch carries the complete target definition. A
Scenario <-> Scenario Outline switch stays Cucumber and carries the Gherkin
even when the text alone is unchanged. The summary comparison only detects a
rename; it never blocks the update of an explicitly matched test. Manual steps
ignore Xray Data when comparing; a rewrite keeps the Data of each step whose
action and expected result are unchanged at the same position.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from domain.test_management.xray import (
    CucumberDefinition,
    IssueLinkRef,
    ManualDefinition,
    XrayTestDetails,
    XrayTestPatch,
    XrayTestSpec,
    XrayTestStep,
)


@dataclass(frozen=True, slots=True)
class DiffProblem:
    """The existing test cannot be updated to the spec; ``reason`` is a fixed code."""

    reason: str


def diff_test(
    spec: XrayTestSpec,
    details: XrayTestDetails,
    *,
    component: str | None,
    story_key: str | None,
    link_type: str,
) -> XrayTestPatch | DiffProblem | None:
    """Return the patch that makes ``details`` match ``spec``; ``None`` when unchanged.

    The component is compared only when ``component`` is set and is only ever
    added. The story link is compared only when ``story_key`` is set: it needs a
    ``link_type`` link pointing outward from the test to the story.
    """
    if details.kind == "other":
        return DiffProblem("unsupported_test_type")
    values: dict[str, object] = {}
    if spec.title != details.summary:
        values["summary"] = spec.title
    target = ManualDefinition(spec.steps) if spec.kind == "manual" else (
        CucumberDefinition(spec.gherkin, spec.outline)
    )
    if spec.kind != details.kind:
        values["kind_change"] = (details.kind, spec.kind)
        values["definition"] = target
    elif spec.kind == "cucumber":
        current_type = details.scenario_type or "scenario"
        wanted_type = "scenario_outline" if spec.outline else "scenario"
        if current_type != wanted_type:
            values["scenario_type_change"] = (current_type, wanted_type)
            values["definition"] = target
        elif _normalized(spec.gherkin) != _normalized(details.gherkin):
            values["definition"] = target
    elif not _same_steps(spec, details):
        values["definition"] = ManualDefinition(_keep_data(spec, details))
    if component and component not in details.components:
        values["add_component"] = component
    if story_key is not None:
        required = IssueLinkRef(link_type, "outward", story_key)
        if required not in details.links:
            values["add_story_link"] = required
    if not values:
        return None
    return XrayTestPatch(key=details.key, issue_id=details.issue_id, **values)  # type: ignore[arg-type]


def _same_steps(spec: XrayTestSpec, details: XrayTestDetails) -> bool:
    if len(spec.steps) != len(details.steps):
        return False
    return all(
        _same_step(want, have) for want, have in zip(spec.steps, details.steps, strict=True)
    )


def _keep_data(spec: XrayTestSpec, details: XrayTestDetails) -> tuple[XrayTestStep, ...]:
    """Spec steps, keeping the existing Data of a step unchanged at the same position."""
    steps: list[XrayTestStep] = []
    for index, want in enumerate(spec.steps):
        have = details.steps[index] if index < len(details.steps) else None
        if have is not None and not want.data and _same_step(want, have):
            want = replace(want, data=have.data)
        steps.append(want)
    return tuple(steps)


def _same_step(want: XrayTestStep, have: XrayTestStep) -> bool:
    return _normalized(want.action) == _normalized(have.action) and _normalized(
        want.expected
    ) == _normalized(have.expected)


def _normalized(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")
