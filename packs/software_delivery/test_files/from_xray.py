"""Render Xray test details as Robot / Gherkin scenario text (#400).

Inverse of ``xray_specs.build_spec``. Never silently flattens outlines, tables
or doc strings when the target format cannot preserve them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from domain.test_management.xray import XrayTestDetails, XrayTestStep
from packs.software_delivery.test_files.models import TestFileTagConfig

PullFormat = str  # "robot" | "feature"

_ROBOT_SEPARATOR = re.compile(r"\s{2,}|\t")


@dataclass(frozen=True, slots=True)
class ScenarioRender:
    """One scenario block ready to insert or start a new file."""

    format: PullFormat
    summary: str
    key: str
    text: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RenderUnsupported:
    reason: str
    warnings: tuple[str, ...] = ()


def render_scenario(
    details: XrayTestDetails,
    fmt: PullFormat,
    tags: TestFileTagConfig,
) -> ScenarioRender | RenderUnsupported:
    """Convert one Xray test into a ``.robot`` or ``.feature`` scenario block."""
    warnings = (("preconditions_present",) if details.preconditions > 0 else ())
    if details.kind == "other":
        return RenderUnsupported("other_kind", warnings)
    if fmt == "robot" and _ROBOT_SEPARATOR.search(details.summary):
        return RenderUnsupported("robot_summary_separator", warnings)
    if details.kind == "cucumber":
        return _cucumber(details, fmt, tags, warnings)
    return _manual(details, fmt, tags, warnings)


def new_file_text(
    *,
    fmt: PullFormat,
    story_key: str,
    story_summary: str,
    scenarios: tuple[ScenarioRender, ...],
    tags: TestFileTagConfig,
) -> str:
    """Full new suite/feature file with configured story markers and scenarios."""
    body = "\n\n".join(s.text.rstrip("\n") for s in scenarios)
    if fmt == "robot":
        story_tag = f"{tags.story_marker}    {story_key}"
        return (
            "*** Settings ***\n"
            f"Default Tags    {story_tag}\n\n"
            "*** Test Cases ***\n"
            f"{body}\n"
        )
    story = f"@{tags.story_marker}:{story_key}"
    return f"{story}\nFeature: [{story_key}] {story_summary}\n\n{body}\n"


def _cucumber(
    details: XrayTestDetails,
    fmt: PullFormat,
    tags: TestFileTagConfig,
    warnings: tuple[str, ...],
) -> ScenarioRender | RenderUnsupported:
    gherkin = details.gherkin.strip("\n")
    if not gherkin and details.scenario_type is None:
        return _scaffold(details, fmt, tags, warnings)
    outline = _is_outline(details.scenario_type, gherkin)
    if fmt == "robot":
        if outline:
            return RenderUnsupported("robot_outline_unsupported", warnings)
        if _has_table(gherkin):
            return RenderUnsupported("table_unsupported", warnings)
        if _has_doc_string(gherkin):
            return RenderUnsupported("doc_string_unsupported", warnings)
        steps = _robot_steps_from_gherkin(gherkin)
        text = _robot_scenario(details.summary, details.key, tags, steps, plain=())
        return ScenarioRender("robot", details.summary, details.key, text, warnings)
    keyword = "Scenario Outline" if outline else "Scenario"
    tag = f"@{tags.test_marker}:{details.key}"
    indented = "\n".join(f"  {line}" if line else "" for line in gherkin.splitlines())
    text = f"  {tag}\n  {keyword}: {details.summary}\n{indented}"
    return ScenarioRender("feature", details.summary, details.key, text, warnings)


def _manual(
    details: XrayTestDetails,
    fmt: PullFormat,
    tags: TestFileTagConfig,
    warnings: tuple[str, ...],
) -> ScenarioRender | RenderUnsupported:
    if not details.steps:
        return _scaffold(details, fmt, tags, warnings)
    converted: list[str] = []
    for step in details.steps:
        built = _manual_step_lines(step, fmt)
        if isinstance(built, RenderUnsupported):
            return RenderUnsupported(built.reason, warnings)
        converted.extend(built)
    plain = (_manual_tag(tags),)
    if fmt == "robot":
        text = _robot_scenario(details.summary, details.key, tags, converted, plain=plain)
        return ScenarioRender("robot", details.summary, details.key, text, warnings)
    tag_line = " ".join(
        [f"@{tags.test_marker}:{details.key}", *[f"@{p}" for p in plain]]
    )
    body = "\n".join(f"    {line}" for line in converted)
    text = f"  {tag_line}\n  Scenario: {details.summary}\n{body}"
    return ScenarioRender("feature", details.summary, details.key, text, warnings)


def _manual_step_lines(
    step: XrayTestStep, fmt: PullFormat
) -> list[str] | RenderUnsupported:
    action_lines = _text_lines(step.action)
    if not action_lines:
        return RenderUnsupported("empty_action_step")
    data_lines = _text_lines(step.data or "")
    lines: list[str] = []
    for index, part in enumerate(action_lines):
        lines.append(f"{'Given' if index == 0 else 'And'} {part}")
        if index == 0:
            continuation = "...    " if fmt == "robot" else "And "
            lines.extend(f"{continuation}{chunk}" for chunk in data_lines)
    for index, part in enumerate(_text_lines(step.expected)):
        lines.append(f"{'Then' if index == 0 else 'And'} {part}")
    return lines


def _text_lines(text: str) -> list[str]:
    """Non-blank, trimmed lines of a multi-line Xray step field."""
    return [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]


def _scaffold(
    details: XrayTestDetails,
    fmt: PullFormat,
    tags: TestFileTagConfig,
    warnings: tuple[str, ...],
) -> ScenarioRender:
    scaffold = _scaffold_tag(tags)
    plain = (scaffold,)
    todo = "Given TODO: flesh out this imported test"
    if fmt == "robot":
        text = _robot_scenario(details.summary, details.key, tags, [todo], plain=plain)
        return ScenarioRender("robot", details.summary, details.key, text, warnings)
    tag_line = " ".join([f"@{tags.test_marker}:{details.key}", f"@{scaffold}"])
    text = f"  {tag_line}\n  Scenario: {details.summary}\n    {todo}"
    return ScenarioRender("feature", details.summary, details.key, text, warnings)


def _robot_scenario(
    summary: str,
    key: str,
    tags: TestFileTagConfig,
    steps: list[str],
    *,
    plain: tuple[str, ...],
) -> str:
    tag_cells = [f"{tags.test_marker}:{key}", *plain]
    tag_line = "    [Tags]    " + "    ".join(tag_cells)
    body = "\n".join(f"    {step}" for step in steps)
    return f"Scenario: {summary}\n{tag_line}\n{body}"


def with_story_tag(render: ScenarioRender, story_key: str, tags: TestFileTagConfig) -> ScenarioRender:
    """Robot block carrying its own story tag, for suites without a file-level story."""
    xray_cell = f"[Tags]    {tags.test_marker}:{render.key}"
    story_cell = f"{tags.story_marker}:{story_key}"
    text = render.text.replace(xray_cell, f"{xray_cell}    {story_cell}", 1)
    return replace(render, text=text)


def _scaffold_tag(tags: TestFileTagConfig) -> str:
    return next((t for t in tags.manual_tags if t.casefold() == "scaffold"), tags.manual_tags[0])


def _manual_tag(tags: TestFileTagConfig) -> str:
    scaffold = _scaffold_tag(tags)
    return next((t for t in tags.manual_tags if t != scaffold), scaffold)


def _robot_steps_from_gherkin(gherkin: str) -> list[str]:
    return [line.strip() for line in gherkin.splitlines() if line.strip()]


def _is_outline(scenario_type: str | None, gherkin: str) -> bool:
    if scenario_type is not None:
        return scenario_type == "scenario_outline"
    return any(line.strip().casefold().startswith("examples:") for line in gherkin.splitlines())


def _has_table(gherkin: str) -> bool:
    return any(line.strip().startswith("|") for line in gherkin.splitlines())


def _has_doc_string(gherkin: str) -> bool:
    return '"""' in gherkin or "'''" in gherkin
