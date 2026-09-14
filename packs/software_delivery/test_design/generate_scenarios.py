"""Generate detailed scenarios for selected candidates missing scenarios."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from domain.errors import ToolFailureError
from domain.knowledge import SourceReference
from domain.models import AskResult, Message
from domain.ports import ChatModel
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.limits import (
    SCENARIO_GENERATION_MODEL_SETTINGS,
)
from packs.software_delivery.test_design.model_json import loads_model_json_object
from packs.software_delivery.test_design.models import (
    TestCandidate,
    TestCoverageDraft,
    TestScenario,
)
from packs.software_delivery.test_design.repository import TestCoverageDraftRepository

SCENARIO_GENERATION_SYSTEM = """\
You are a software-delivery scenario author. Generate detailed editable test \
scenarios only for the selected coverage candidates provided in the request.

Rules:
- Return compact JSON only (no markdown fences, no commentary) with key \
"scenarios".
- Each scenario needs scenario_id, candidate_id, title, category, \
preconditions, steps, expected_result, and evidence_references.
- Keep steps and expected_result concise.
- Use only candidate ids supplied in the request.
- Cite only evidence_references already attached to those candidates.
- Do not invent unsupported behaviour.
"""


@dataclass(frozen=True, slots=True)
class GenerateScenariosRequest:
    """Generate-missing-only scenarios for the current draft selection."""

    draft_id: str
    expected_version: int


class GenerateScenarios:
    """Fill missing scenarios for selected candidates; preserve existing edits."""

    def __init__(
        self,
        *,
        chat_model: ChatModel,
        repository: TestCoverageDraftRepository,
    ) -> None:
        self._chat_model = chat_model
        self._repository = repository

    def execute(self, request: GenerateScenariosRequest) -> TestCoverageDraft:
        """Generate missing scenarios and persist with CAS version bump."""
        if not isinstance(request.draft_id, str) or not request.draft_id.strip():
            raise TestDesignValidationError("draft_id must be non-empty")
        if (
            not isinstance(request.expected_version, int)
            or isinstance(request.expected_version, bool)
            or request.expected_version <= 0
        ):
            raise TestDesignValidationError(
                "expected_version must be a positive integer"
            )

        draft = self._repository.get(request.draft_id)
        if draft is None:
            raise TestDesignValidationError("draft not found")

        selected = [c for c in draft.candidates if c.selected]
        scenarios_by_candidate = {
            scenario.candidate_id: scenario for scenario in draft.scenarios
        }
        missing = [
            candidate
            for candidate in selected
            if candidate.candidate_id not in scenarios_by_candidate
        ]

        generated: tuple[TestScenario, ...] = ()
        if missing:
            result = self._chat_model.complete(
                SCENARIO_GENERATION_SYSTEM,
                (_candidates_message(missing),),
                SCENARIO_GENERATION_MODEL_SETTINGS,
            )
            allowed_refs = {
                candidate.candidate_id: {
                    (ref.source_type, ref.source_id)
                    for ref in candidate.evidence_references
                }
                for candidate in missing
            }
            generated = _parse_scenarios(
                result,
                allowed_candidate_ids={c.candidate_id for c in missing},
                allowed_refs_by_candidate=allowed_refs,
                candidates_by_id={c.candidate_id: c for c in missing},
            )

        merged = _merge_scenarios(draft.scenarios, generated)
        updated = TestCoverageDraft(
            draft_id=draft.draft_id,
            workspace_id=draft.workspace_id,
            conversation_id=draft.conversation_id,
            source_reference=draft.source_reference,
            ticket_identifier=draft.ticket_identifier,
            status="scenario_editing",
            candidates=draft.candidates,
            scenarios=merged,
            coverage_gaps=draft.coverage_gaps,
            version=draft.version,
        )
        return self._repository.update(
            updated, expected_version=request.expected_version
        )


def _candidates_message(candidates: Sequence[TestCandidate]) -> Message:
    lines = ["Generate scenarios for these selected candidates:"]
    for candidate in candidates:
        refs = [
            {
                "source_type": ref.source_type,
                "source_id": ref.source_id,
            }
            for ref in candidate.evidence_references
        ]
        lines.append(
            json.dumps(
                {
                    "candidate_id": candidate.candidate_id,
                    "title": candidate.title,
                    "category": candidate.category,
                    "rationale": candidate.rationale,
                    "evidence_references": refs,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    return Message(role="user", content="\n".join(lines))


def _merge_scenarios(
    existing: Sequence[TestScenario],
    generated: Sequence[TestScenario],
) -> tuple[TestScenario, ...]:
    by_candidate = {scenario.candidate_id: scenario for scenario in existing}
    for scenario in generated:
        # Never overwrite an existing scenario for the same candidate.
        if scenario.candidate_id not in by_candidate:
            by_candidate[scenario.candidate_id] = scenario
    return tuple(by_candidate.values())


def _parse_scenarios(
    result: AskResult,
    *,
    allowed_candidate_ids: set[str],
    allowed_refs_by_candidate: Mapping[str, set[tuple[str, str]]],
    candidates_by_id: Mapping[str, TestCandidate],
) -> tuple[TestScenario, ...]:
    data = loads_model_json_object(
        result.content if isinstance(result.content, str) else "",
        failure_prefix="Scenario generation result",
    )
    raw = data.get("scenarios")
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ToolFailureError("scenarios must be a sequence")
    scenarios: list[TestScenario] = []
    seen_ids: set[str] = set()
    seen_candidates: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            raise ToolFailureError("scenarios items must be objects")
        candidate_id = item.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id not in allowed_candidate_ids:
            raise ToolFailureError(
                "scenarios must reference selected candidate ids awaiting generation"
            )
        if candidate_id in seen_candidates:
            raise ToolFailureError(
                "scenarios items must have unique candidate_id for this generation"
            )
        seen_candidates.add(candidate_id)
        scenario_id = item.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            scenario_id = f"scen-{candidate_id}"
        if scenario_id in seen_ids:
            raise ToolFailureError("scenarios items must have unique scenario_id")
        seen_ids.add(scenario_id)
        refs = _parse_references(
            item.get("evidence_references"),
            allowed_refs_by_candidate.get(candidate_id, set()),
        )
        if not refs:
            refs = candidates_by_id[candidate_id].evidence_references
        try:
            scenarios.append(
                TestScenario(
                    scenario_id=scenario_id,
                    candidate_id=candidate_id,
                    title=item.get("title", candidates_by_id[candidate_id].title),
                    category=item.get(
                        "category", candidates_by_id[candidate_id].category
                    ),
                    preconditions=item.get("preconditions", ()),
                    steps=item["steps"],  # type: ignore[arg-type]
                    expected_result=item["expected_result"],  # type: ignore[arg-type]
                    evidence_references=refs,
                )
            )
        except TestDesignValidationError as error:
            raise ToolFailureError(
                "Scenario generation result failed scenario validation"
            ) from error
        except Exception as error:
            raise ToolFailureError(
                "Scenario generation result missing required fields"
            ) from error
    missing_ids = allowed_candidate_ids - seen_candidates
    if missing_ids:
        raise ToolFailureError(
            "Scenario generation result omitted selected candidates"
        )
    return tuple(scenarios)


def _parse_references(
    raw: object,
    allowed_refs: set[tuple[str, str]],
) -> tuple[SourceReference, ...]:
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ToolFailureError("evidence_references must be a sequence")
    refs: list[SourceReference] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ToolFailureError("evidence_references items must be objects")
        source_id = item.get("source_id")
        source_type = item.get("source_type")
        if not isinstance(source_id, str) or not isinstance(source_type, str):
            raise ToolFailureError(
                "evidence_references items must use string source fields"
            )
        if (source_type, source_id) not in allowed_refs:
            raise ToolFailureError(
                "evidence_references must cite sources from the candidate"
            )
        refs.append(SourceReference(source_id, source_type))
    return tuple(refs)
