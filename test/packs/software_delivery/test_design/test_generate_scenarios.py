"""Tests for selected-candidate scenario generation use case."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace

import pytest

from domain.errors import ToolFailureError
from domain.knowledge import SourceReference
from domain.models import AskResult, Message
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.generate_scenarios import (
    GenerateScenarios,
    GenerateScenariosRequest,
)
from packs.software_delivery.test_design.models import (
    TestCandidate,
    TestCoverageDraft,
    TestScenario,
)


class _FakeChat:
    def __init__(self, content: str = "") -> None:
        self.content = content
        self.calls: list[tuple[str, Sequence[Message], Mapping[str, object]]] = []

    def complete(
        self,
        system: str,
        messages: Sequence[Message],
        settings: Mapping[str, object],
    ) -> AskResult:
        self.calls.append((system, tuple(messages), dict(settings)))
        return AskResult(content=self.content, model="fake")


class _MemoryRepo:
    def __init__(self, draft: TestCoverageDraft) -> None:
        self._draft = draft

    def create(self, draft: TestCoverageDraft) -> TestCoverageDraft:
        raise NotImplementedError

    def get(self, draft_id: str) -> TestCoverageDraft | None:
        if draft_id != self._draft.draft_id:
            return None
        return self._draft

    def update(
        self, draft: TestCoverageDraft, *, expected_version: int
    ) -> TestCoverageDraft:
        if expected_version != self._draft.version:
            raise RuntimeError("version conflict")
        self._draft = replace(draft, version=expected_version + 1)
        return self._draft


def _ref() -> SourceReference:
    return SourceReference("PROJ-42", "jira")


def _candidate(
    candidate_id: str,
    *,
    selected: bool = True,
    title: str | None = None,
) -> TestCandidate:
    return TestCandidate(
        candidate_id=candidate_id,
        title=title or f"Title for {candidate_id}",
        category="happy_path",
        rationale="Supported by acceptance criteria.",
        evidence_references=(_ref(),),
        selected=selected,
        origin="suggested",
    )


def _scenario(candidate_id: str, *, scenario_id: str | None = None) -> TestScenario:
    return TestScenario(
        scenario_id=scenario_id or f"scen-{candidate_id}",
        candidate_id=candidate_id,
        title=f"Scenario for {candidate_id}",
        category="happy_path",
        preconditions=("User exists",),
        steps=("Open login", "Submit"),
        expected_result="Dashboard shown",
        evidence_references=(_ref(),),
    )


def _draft(
    *,
    candidates: Sequence[TestCandidate],
    scenarios: Sequence[TestScenario] = (),
    version: int = 1,
    status: str = "coverage_review",
) -> TestCoverageDraft:
    return TestCoverageDraft(
        draft_id="draft-1",
        workspace_id="ws-1",
        conversation_id="conv-1",
        source_reference=_ref(),
        ticket_identifier="KERN-293",
        status=status,  # type: ignore[arg-type]
        candidates=tuple(candidates),
        scenarios=tuple(scenarios),
        coverage_gaps=(),
        version=version,
    )


def _model_scenarios(*candidate_ids: str) -> str:
    return json.dumps(
        {
            "scenarios": [
                {
                    "scenario_id": f"scen-{candidate_id}",
                    "candidate_id": candidate_id,
                    "title": f"Generated for {candidate_id}",
                    "category": "happy_path",
                    "preconditions": ["Account active"],
                    "steps": ["Open /login", "Enter credentials", "Submit"],
                    "expected_result": "User reaches dashboard",
                    "evidence_references": [
                        {"source_type": "jira", "source_id": "PROJ-42"}
                    ],
                }
                for candidate_id in candidate_ids
            ]
        }
    )


def test_generates_only_for_selected_missing_scenarios() -> None:
    draft = _draft(
        candidates=(
            _candidate("cand-1", selected=True),
            _candidate("cand-2", selected=True),
            _candidate("cand-3", selected=False),
        ),
        scenarios=(_scenario("cand-1"),),
        version=2,
    )
    chat = _FakeChat(content=_model_scenarios("cand-2"))
    repo = _MemoryRepo(draft)
    use_case = GenerateScenarios(chat_model=chat, repository=repo)

    result = use_case.execute(
        GenerateScenariosRequest(draft_id="draft-1", expected_version=2)
    )

    assert result.status == "scenario_editing"
    assert result.version == 3
    assert {s.candidate_id for s in result.scenarios} == {"cand-1", "cand-2"}
    preserved = next(s for s in result.scenarios if s.candidate_id == "cand-1")
    assert preserved.title == "Scenario for cand-1"
    assert preserved.steps == ("Open login", "Submit")
    generated = next(s for s in result.scenarios if s.candidate_id == "cand-2")
    assert generated.title == "Generated for cand-2"
    assert len(chat.calls) == 1


def test_does_not_call_model_when_selected_already_have_scenarios() -> None:
    draft = _draft(
        candidates=(_candidate("cand-1"),),
        scenarios=(_scenario("cand-1"),),
        version=2,
        status="scenario_editing",
    )
    chat = _FakeChat(content=_model_scenarios("cand-1"))
    repo = _MemoryRepo(draft)
    use_case = GenerateScenarios(chat_model=chat, repository=repo)

    result = use_case.execute(
        GenerateScenariosRequest(draft_id="draft-1", expected_version=2)
    )

    assert chat.calls == []
    assert result.version == 3
    assert result.scenarios[0].title == "Scenario for cand-1"
    assert result.status == "scenario_editing"


def test_preserves_scenario_for_deselected_candidate() -> None:
    draft = _draft(
        candidates=(
            _candidate("cand-1", selected=False),
            _candidate("cand-2", selected=True),
        ),
        scenarios=(_scenario("cand-1"),),
        version=4,
    )
    chat = _FakeChat(content=_model_scenarios("cand-2"))
    repo = _MemoryRepo(draft)
    use_case = GenerateScenarios(chat_model=chat, repository=repo)

    result = use_case.execute(
        GenerateScenariosRequest(draft_id="draft-1", expected_version=4)
    )

    assert {s.candidate_id for s in result.scenarios} == {"cand-1", "cand-2"}
    assert next(s for s in result.scenarios if s.candidate_id == "cand-1").title == (
        "Scenario for cand-1"
    )


def test_missing_draft_raises_validation_error() -> None:
    chat = _FakeChat(content=_model_scenarios("cand-1"))
    repo = _MemoryRepo(_draft(candidates=(_candidate("cand-1"),)))
    use_case = GenerateScenarios(chat_model=chat, repository=repo)

    with pytest.raises(TestDesignValidationError, match="draft"):
        use_case.execute(
            GenerateScenariosRequest(draft_id="missing", expected_version=1)
        )


def test_invalid_model_json_does_not_overwrite_scenarios() -> None:
    draft = _draft(
        candidates=(_candidate("cand-1"), _candidate("cand-2")),
        scenarios=(_scenario("cand-1"),),
        version=2,
    )
    chat = _FakeChat(content="not-json")
    repo = _MemoryRepo(draft)
    use_case = GenerateScenarios(chat_model=chat, repository=repo)

    with pytest.raises(ToolFailureError, match="JSON"):
        use_case.execute(
            GenerateScenariosRequest(draft_id="draft-1", expected_version=2)
        )

    assert repo.get("draft-1").scenarios == (_scenario("cand-1"),)
    assert repo.get("draft-1").version == 2
