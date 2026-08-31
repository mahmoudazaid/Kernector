"""ChatModel-backed Software Delivery test-case generation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from domain.errors import ProviderError, ToolFailureError
from domain.knowledge import SourceReference
from domain.models import AskResult
from domain.ports import ChatModel
from packs.software_delivery.contracts import (
    GeneratedTestCase,
    TestCaseStyle,
    TestGenerationRequest,
    TestGenerationResult,
)
from packs.software_delivery.gherkin import parse_gherkin_steps
from packs.software_delivery.limits import (
    MAX_EVIDENCE_IDS_PER_CASE,
    MAX_EXPECTED_CHARS,
    MAX_GENERATED_CASES,
    MAX_MODEL_RESPONSE_CHARS,
    MAX_STEP_CHARS,
    MAX_STEPS_PER_CASE,
    MAX_TITLE_CHARS,
    MAX_TOTAL_OUTPUT_CHARS,
    TEST_GENERATION_MODEL_SETTINGS,
)
from packs.software_delivery.test_case_prompt import build_test_case_prompt

_CASE_KEYS_STEPS = frozenset({"title", "steps", "expected", "evidence_ids"})
_CASE_KEYS_GHERKIN = frozenset({"title", "steps", "evidence_ids"})


def generate_test_cases(
    request: TestGenerationRequest,
    chat_model: ChatModel,
) -> TestGenerationResult:
    """Generate structured test cases via ChatModel and trusted provenance mapping.

    Raises:
        TestCaseGenerationValidationError: Propagated from prompt/budget checks
            before the model is invoked.
        ToolFailureError: Provider failure or invalid model output.
    """
    system, messages, evidence_by_id = build_test_case_prompt(request)
    try:
        result = chat_model.complete(
            system, messages, dict(TEST_GENERATION_MODEL_SETTINGS)
        )
    except ProviderError as exc:
        raise ToolFailureError("Test case generation model call failed") from exc
    except Exception as exc:  # noqa: BLE001 - operational failure after valid args
        raise ToolFailureError("Test case generation failed") from exc

    if not isinstance(result, AskResult) or not isinstance(result.content, str):
        raise ToolFailureError("Test case generation returned unusable model content")
    if len(result.content) > MAX_MODEL_RESPONSE_CHARS:
        raise ToolFailureError(
            f"model response must be at most {MAX_MODEL_RESPONSE_CHARS} characters, "
            f"got {len(result.content)}"
        )

    try:
        payload = json.loads(result.content)
    except json.JSONDecodeError as exc:
        raise ToolFailureError("model response is not valid JSON") from exc

    cases = _parse_cases(payload, request.output_style, evidence_by_id)
    outcome = TestGenerationResult(request.output_style, cases)
    # Enforce the public serializer budget before returning (same gate as the tool).
    serialize_test_generation_result(outcome)
    return outcome


def serialize_test_generation_result(result: TestGenerationResult) -> str:
    """Serialize a validated result to opaque tool JSON.

    Enforces ``MAX_TOTAL_OUTPUT_CHARS`` on the final JSON so injected generators
    and the default pipeline share one budget boundary.

    Raises:
        ToolFailureError: Serialization failed or the JSON exceeds the budget.
    """
    try:
        serialized = _serialize_result(result)
    except ToolFailureError:
        raise
    except Exception as exc:  # noqa: BLE001 - map serialization failures
        raise ToolFailureError(
            "Failed to serialize test generation result"
        ) from exc
    if len(serialized) > MAX_TOTAL_OUTPUT_CHARS:
        raise ToolFailureError(
            f"serialized result must be at most {MAX_TOTAL_OUTPUT_CHARS} characters, "
            f"got {len(serialized)}"
        )
    return serialized


def _serialize_result(result: TestGenerationResult) -> str:
    payload: dict[str, Any] = {
        "output_style": result.output_style,
        "test_cases": [
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
            for case in result.test_cases
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _parse_cases(
    payload: object,
    style: TestCaseStyle,
    evidence_by_id: Mapping[str, SourceReference],
) -> tuple[GeneratedTestCase, ...]:
    if not isinstance(payload, dict):
        raise ToolFailureError("model JSON must be an object")
    if "output_style" in payload:
        raise ToolFailureError("model must not supply output_style")
    unknown_root = set(payload) - {"test_cases"}
    if unknown_root:
        raise ToolFailureError(
            f"unexpected model fields: {sorted(unknown_root)}"
        )
    if "test_cases" not in payload:
        raise ToolFailureError("test_cases is required")
    raw_cases = payload["test_cases"]
    if isinstance(raw_cases, (str, bytes)) or not isinstance(raw_cases, Sequence):
        raise ToolFailureError("test_cases must be a sequence")
    if len(raw_cases) == 0:
        raise ToolFailureError("test_cases must be non-empty")
    if len(raw_cases) > MAX_GENERATED_CASES:
        raise ToolFailureError(
            f"test_cases must have at most {MAX_GENERATED_CASES} items"
        )

    parsed: list[GeneratedTestCase] = []
    for item in raw_cases:
        parsed.append(_parse_case(item, style, evidence_by_id))
    return tuple(parsed)


def _parse_case(
    item: object,
    style: TestCaseStyle,
    evidence_by_id: Mapping[str, SourceReference],
) -> GeneratedTestCase:
    if not isinstance(item, Mapping):
        raise ToolFailureError("test case must be an object")
    for key in item:
        if not isinstance(key, str):
            raise ToolFailureError("test case keys must be strings")
    allowed = _CASE_KEYS_STEPS if style == "steps" else _CASE_KEYS_GHERKIN
    unknown = set(item) - allowed
    if unknown:
        raise ToolFailureError(f"unexpected test case fields: {sorted(unknown)}")
    if "expected" in item and style == "gherkin":
        raise ToolFailureError("gherkin model output must not include expected")
    for required in ("title", "steps", "evidence_ids"):
        if required not in item:
            raise ToolFailureError(f"{required} is required")
    if style == "steps" and "expected" not in item:
        raise ToolFailureError("expected is required")

    title = item["title"]
    if not isinstance(title, str) or not title.strip():
        raise ToolFailureError("title must be a non-blank string")
    if len(title) > MAX_TITLE_CHARS:
        raise ToolFailureError(
            f"title must be at most {MAX_TITLE_CHARS} characters"
        )

    raw_steps = item["steps"]
    if isinstance(raw_steps, (str, bytes)) or not isinstance(raw_steps, Sequence):
        raise ToolFailureError("steps must be a sequence")
    if len(raw_steps) == 0:
        raise ToolFailureError("steps must be non-empty")
    if len(raw_steps) > MAX_STEPS_PER_CASE:
        raise ToolFailureError(
            f"steps must have at most {MAX_STEPS_PER_CASE} items"
        )
    steps: list[str] = []
    for step in raw_steps:
        if not isinstance(step, str) or not step.strip():
            raise ToolFailureError("steps items must be non-blank strings")
        if len(step) > MAX_STEP_CHARS:
            raise ToolFailureError(
                f"step must be at most {MAX_STEP_CHARS} characters"
            )
        steps.append(step)

    if style == "steps":
        expected = item["expected"]
        if not isinstance(expected, str) or not expected.strip():
            raise ToolFailureError("expected must be a non-blank string")
        if len(expected) > MAX_EXPECTED_CHARS:
            raise ToolFailureError(
                f"expected must be at most {MAX_EXPECTED_CHARS} characters"
            )
        normalized_steps: tuple[str, ...] = tuple(steps)
    else:
        try:
            normalized_steps, expected = parse_gherkin_steps(steps)
        except ValueError as exc:
            raise ToolFailureError(str(exc)) from exc
        if len(expected) > MAX_EXPECTED_CHARS:
            raise ToolFailureError(
                f"expected must be at most {MAX_EXPECTED_CHARS} characters"
            )

    references = _resolve_evidence_ids(item["evidence_ids"], evidence_by_id)
    try:
        return GeneratedTestCase(title, normalized_steps, expected, references)
    except ValueError as exc:
        raise ToolFailureError(str(exc)) from exc


def _resolve_evidence_ids(
    raw_ids: object,
    evidence_by_id: Mapping[str, SourceReference],
) -> tuple[SourceReference, ...]:
    if isinstance(raw_ids, (str, bytes)) or not isinstance(raw_ids, Sequence):
        raise ToolFailureError("evidence_ids must be a sequence")
    if len(raw_ids) == 0:
        raise ToolFailureError("evidence_ids must be non-empty")
    if len(raw_ids) > MAX_EVIDENCE_IDS_PER_CASE:
        raise ToolFailureError(
            f"evidence_ids must have at most {MAX_EVIDENCE_IDS_PER_CASE} items"
        )
    refs: list[SourceReference] = []
    for evidence_id in raw_ids:
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ToolFailureError("evidence_ids items must be non-blank strings")
        if evidence_id not in evidence_by_id:
            raise ToolFailureError(f"unknown evidence_id: {evidence_id!r}")
        refs.append(evidence_by_id[evidence_id])
    return tuple(refs)
