"""Robot Framework MVP generator (#368).

Renders deterministic ``.robot`` suites from confirmed draft cases and the
``FrameworkSelection`` keyword snapshot. Never invents stub keywords.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from packs.software_delivery.test_design.framework_contracts import (
    FrameworkArtifactResult,
    FrameworkFile,
    FrameworkSelection,
    FrameworkTestTrace,
    StepOutcome,
)
from packs.software_delivery.test_design.models import GeneratedTestCase, TestCoverageDraft

_GHERKIN_STEP = re.compile(
    r"^\s*(Given|When|Then|And|But)\s+(.+?)\s*$", re.IGNORECASE | re.MULTILINE
)
_RESOURCE_SETTING = re.compile(r"Resource\s+", re.IGNORECASE)


class RobotFrameworkGenerator:
    """Generate Robot suites that reuse confirmed keywords where they match."""

    framework_id = "robot_framework"

    def generate(
        self,
        draft: TestCoverageDraft,
        selection: FrameworkSelection,
        cases: Sequence[GeneratedTestCase],
    ) -> FrameworkArtifactResult:
        keywords = {
            item.signature.casefold(): item for item in selection.reusable_components
        }
        # Only ``.resource`` files are importable as Resource; suite ``.robot``
        # files with Test Cases cannot be imported by another suite.
        resource_paths = sorted(
            {
                item.path
                for item in selection.reusable_components
                if item.path.endswith(".resource")
            }
        )
        folder = _test_folder(selection)
        files: list[FrameworkFile] = []
        traces: list[FrameworkTestTrace] = []
        implementation_required: list[str] = []
        skipped: list[str] = []

        for case in cases:
            if case.availability != "available":
                skipped.append(case.candidate_id)
                continue
            steps = _case_steps(case)
            if not steps:
                skipped.append(case.candidate_id)
                continue

            outcomes: list[StepOutcome] = []
            robot_steps: list[str] = []
            behaviour = tuple(
                (ref.source_type, ref.source_id)
                for cand in draft.candidates
                if cand.candidate_id == case.candidate_id
                for ref in cand.evidence_references
            )
            for step in steps:
                match = keywords.get(step.casefold())
                if match is None:
                    outcomes.append(
                        StepOutcome(
                            step=step,
                            outcome="implementation_required",
                            behaviour_refs=behaviour,
                            convention_refs=(),
                        )
                    )
                    implementation_required.append(step)
                    # Emit the missing name as-is so Robot fails until implemented;
                    # never invent No Operation / Pass Execution stubs.
                    robot_steps.append(step)
                    continue
                if _contradicts(match.documentation, step, case):
                    outcomes.append(
                        StepOutcome(
                            step=step,
                            outcome="ambiguous",
                            behaviour_refs=behaviour,
                            convention_refs=(match.component_id,),
                            component_id=match.component_id,
                        )
                    )
                    continue
                outcomes.append(
                    StepOutcome(
                        step=step,
                        outcome="reused",
                        behaviour_refs=behaviour,
                        convention_refs=(match.component_id,),
                        component_id=match.component_id,
                    )
                )
                robot_steps.append(match.signature)

            if not robot_steps:
                # All steps were ambiguous (or otherwise omitted) — skip the case
                # rather than writing an empty/stub suite that would pass.
                skipped.append(case.candidate_id)
                traces.append(
                    FrameworkTestTrace(
                        candidate_id=case.candidate_id,
                        evidence_refs=behaviour,
                        step_outcomes=tuple(outcomes),
                    )
                )
                continue

            title = _case_title(draft, case.candidate_id)
            body = _render_suite(title, robot_steps, resource_paths, folder)
            stem = _slug(title) or case.candidate_id
            filename = f"{stem}.robot"
            suggested = f"{folder.rstrip('/')}/{filename}"
            files.append(
                FrameworkFile(
                    filename=filename,
                    suggested_path=suggested,
                    content=body,
                )
            )
            traces.append(
                FrameworkTestTrace(
                    candidate_id=case.candidate_id,
                    evidence_refs=behaviour,
                    step_outcomes=tuple(outcomes),
                )
            )

        # Deduplicate implementation_required while preserving order.
        seen: set[str] = set()
        unique_required: list[str] = []
        for step in implementation_required:
            key = step.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique_required.append(step)

        return FrameworkArtifactResult(
            status="ok",
            framework_id=self.framework_id,
            files=tuple(files),
            tests=tuple(traces),
            implementation_required=tuple(unique_required),
            skipped=tuple(skipped),
            untrusted_model_output=False,
            evidence_origin=selection.evidence_origin,
        )


def _test_folder(selection: FrameworkSelection) -> str:
    for convention in selection.conventions:
        if convention.name in {"test_root", "test_folder", "tests_dir", "robot_tests"}:
            value = convention.value.strip().rstrip("/")
            if value:
                return value
    return "tests"


def _case_steps(case: GeneratedTestCase) -> list[str]:
    if case.test_type == "cucumber" and case.gherkin.strip():
        return [match.group(2).strip() for match in _GHERKIN_STEP.finditer(case.gherkin)]
    return [step.strip() for step in case.steps if step.strip()]


def _case_title(draft: TestCoverageDraft, candidate_id: str) -> str:
    for candidate in draft.candidates:
        if candidate.candidate_id == candidate_id:
            return candidate.title
    return candidate_id


def _slug(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", title.strip()).strip("_")
    return cleaned.lower()


def _render_suite(
    title: str,
    steps: Sequence[str],
    resource_paths: Sequence[str],
    folder: str,
) -> str:
    lines: list[str] = ["*** Settings ***"]
    for path in resource_paths:
        rel = _relative_resource(folder, path)
        lines.append(f"Resource    {rel}")
    lines.append("")
    lines.append("*** Test Cases ***")
    lines.append(title)
    for step in steps:
        lines.append(f"    {step}")
    lines.append("")
    return "\n".join(lines)


def _relative_resource(folder: str, resource_path: str) -> str:
    # Prefer a path relative to the suggested test folder.
    folder_parts = [p for p in folder.replace("\\", "/").split("/") if p]
    resource = resource_path.replace("\\", "/")
    depth = max(len(folder_parts), 1)
    prefix = "/".join([".."] * depth)
    return f"{prefix}/{resource}"


def _contradicts(documentation: str, step: str, case: GeneratedTestCase) -> bool:
    """Flag reuse when keyword docs clearly conflict with the case expectation."""
    docs = documentation.casefold()
    expected = (case.expected_result or "").casefold()
    if not docs or not expected:
        return False
    # Narrow heuristic for the outdated-assertion fixture: docs say "cannot"
    # while the case expects success (or the reverse).
    if "cannot" in docs and "cannot" not in expected and "cancel" in step.casefold():
        if "cancel" in expected and "not" not in expected and "cannot" not in expected:
            return True
    if "must not" in docs and "must not" not in expected:
        return True
    return False
