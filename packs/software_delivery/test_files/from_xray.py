"""Render Xray test details as Robot / Gherkin scenario text (#400).

Inverse of ``xray_specs.build_spec``. Never silently flattens outlines, tables
or doc strings when the target format cannot preserve them.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.test_management.xray import XrayTestDetails, XrayTestStep
from packs.software_delivery.test_files.models import TestFileTagConfig

PullFormat = str  # "robot" | "feature"


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
    if fmt == "robot":
        if details.scenario_type == "scenario_outline" or _looks_like_outline(gherkin):
            return RenderUnsupported("robot_outline_unsupported", warnings)
        if _has_table(gherkin):
            return RenderUnsupported("table_unsupported", warnings)
        if _has_doc_string(gherkin):
            return RenderUnsupported("doc_string_unsupported", warnings)
        steps = _robot_steps_from_gherkin(gherkin)
        text = _robot_scenario(details.summary, details.key, tags, steps, plain=())
        return ScenarioRender("robot", details.summary, details.key, text, warnings)
    keyword = "Scenario Outline" if (
        details.scenario_type == "scenario_outline" or _looks_like_outline(gherkin)
    ) else "Scenario"
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
    plain = tuple(tags.manual_tags)
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
    action = step.action.replace("\r\n", "\n")
    expected = step.expected.replace("\r\n", "\n")
    data = step.data.replace("\r\n", "\n") if step.data else ""
    if not action.strip() and expected.strip():
        return RenderUnsupported("empty_action_step")
    if not action.strip() and not expected.strip():
        return RenderUnsupported("empty_action_step")
    lines: list[str] = []
    action_lines = [part for part in action.split("\n")]
    for index, part in enumerate(action_lines):
        prefix = "Given" if index == 0 else "And"
        content = part if part.strip() else part
        if index == 0 and data.strip():
            content = f"{content}\n{data}" if content.strip() else data
        if fmt == "robot":
            for i, chunk in enumerate(content.split("\n")):
                kw = prefix if i == 0 else "..."
                lines.append(f"{kw} {chunk}" if chunk.strip() or i == 0 else f"{kw}")
        else:
            for i, chunk in enumerate(content.split("\n")):
                kw = prefix if i == 0 else "And"
                lines.append(f"{kw} {chunk}".rstrip())
    if expected.strip():
        expected_lines = expected.split("\n")
        for index, part in enumerate(expected_lines):
            prefix = "Then" if index == 0 else "And"
            if fmt == "robot":
                lines.append(f"{prefix} {part}")
            else:
                lines.append(f"{prefix} {part}".rstrip())
    return lines


def _scaffold(
    details: XrayTestDetails,
    fmt: PullFormat,
    tags: TestFileTagConfig,
    warnings: tuple[str, ...],
) -> ScenarioRender:
    scaffold = next((t for t in tags.manual_tags if t.casefold() == "scaffold"), tags.manual_tags[0])
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


def _robot_steps_from_gherkin(gherkin: str) -> list[str]:
    return [line.strip() for line in gherkin.splitlines() if line.strip()]


def _looks_like_outline(gherkin: str) -> bool:
    lower = gherkin.casefold()
    return "examples:" in lower or "<" in gherkin and ">" in gherkin


def _has_table(gherkin: str) -> bool:
    return any(line.strip().startswith("|") for line in gherkin.splitlines())


def _has_doc_string(gherkin: str) -> bool:
    return '"""' in gherkin or "'''" in gherkin
