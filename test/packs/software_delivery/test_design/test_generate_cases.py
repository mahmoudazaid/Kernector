"""Tests for test-design generate-cases use case (#300)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace

import pytest

from domain.errors import ToolFailureError
from domain.knowledge import SourceReference
from domain.models import AskResult, Message
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.generate_cases import (
    GenerateTestCases,
    GenerateTestCasesRequest,
    TypeOverride,
)
from packs.software_delivery.test_design.models import (
    GeneratedTestCase,
    TestCandidate,
    TestCoverageDraft,
)
from packs.software_delivery.test_design.suggest_tests import CoverageEvidenceItem


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
        self._by_id = {draft.draft_id: draft}
        self.updates: list[tuple[TestCoverageDraft, int]] = []

    def create(self, draft: TestCoverageDraft) -> TestCoverageDraft:
        raise NotImplementedError

    def get(self, draft_id: str) -> TestCoverageDraft | None:
        return self._by_id.get(draft_id)

    def update(
        self, draft: TestCoverageDraft, *, expected_version: int
    ) -> TestCoverageDraft:
        current = self._by_id[draft.draft_id]
        if current.version != expected_version:
            raise RuntimeError("version conflict")
        saved = replace(draft, version=expected_version + 1)
        self._by_id[draft.draft_id] = saved
        self.updates.append((draft, expected_version))
        return saved


def _ref(source_id: str = "issue:I_1", source_type: str = "github") -> SourceReference:
    return SourceReference(source_id, source_type)


def _candidate(**overrides: object) -> TestCandidate:
    base: dict[str, object] = {
        "candidate_id": "cand-1",
        "title": "Valid login",
        "category": "positive",
        "rationale": "AC covers login.",
        "evidence_references": (_ref(),),
        "selected": True,
        "origin": "suggested",
        "test_type": None,
    }
    base.update(overrides)
    return TestCandidate(**base)  # type: ignore[arg-type]


def _draft(**overrides: object) -> TestCoverageDraft:
    base: dict[str, object] = {
        "draft_id": "draft-1",
        "workspace_id": "ws-1",
        "conversation_id": "conv-1",
        "source_reference": _ref(),
        "ticket_identifier": "owner/repo#1",
        "source_provider": "github",
        "status": "ready",
        "candidates": (_candidate(),),
        "version": 2,
        "generated_cases": (),
        "evidence_fingerprint": "fp-1",
    }
    base.update(overrides)
    return TestCoverageDraft(**base)  # type: ignore[arg-type]


def _evidence(text: str = "Users can log in with email.") -> CoverageEvidenceItem:
    return CoverageEvidenceItem(reference=_ref(), text=text)


def _manual_case_payload(
    candidate_id: str = "cand-1",
    *,
    availability: str = "available",
) -> dict[str, object]:
    if availability == "insufficient_evidence":
        return {
            "candidate_id": candidate_id,
            "test_type": "manual",
            "automation_fit": "unclear",
            "automation_rationale": "Issue lacks steps.",
            "availability": "insufficient_evidence",
            "preconditions": "",
            "steps": [],
            "expected_result": "",
            "gherkin": "",
        }
    return {
        "candidate_id": candidate_id,
        "test_type": "manual",
        "automation_fit": "applicable",
        "automation_rationale": "Stable UI path.",
        "availability": "available",
        "preconditions": "User is logged out.",
        "steps": ["Enter credentials", "Submit"],
        "expected_result": "Home page loads.",
        "gherkin": "",
    }


def _cucumber_case_payload(candidate_id: str = "cand-2") -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "test_type": "cucumber",
        "automation_fit": "not_applicable",
        "automation_rationale": "Exploratory edge.",
        "availability": "available",
        "preconditions": "",
        "steps": [],
        "expected_result": "",
        "gherkin": "Scenario: Timeout\n  Given slow network",
    }


def _model_payload(
    cases: Sequence[Mapping[str, object]],
    *,
    cucumber_feature: str = "",
    cucumber_background: str = "",
) -> str:
    body: dict[str, object] = {"cases": list(cases)}
    if cucumber_feature:
        body["cucumber_feature"] = cucumber_feature
    if cucumber_background:
        body["cucumber_background"] = cucumber_background
    return json.dumps(body)


def test_generate_happy_path_persists_case_editing_draft() -> None:
    draft = _draft()
    chat = _FakeChat(content=_model_payload([_manual_case_payload()]))
    repo = _MemoryRepo(draft)
    use_case = GenerateTestCases(chat_model=chat, repository=repo)

    outcome = use_case.execute(
        GenerateTestCasesRequest(
            draft_id="draft-1",
            expected_version=2,
            evidence=(_evidence(),),
            evidence_fingerprint="fp-1",
        )
    )
    result = outcome.draft

    assert result.status == "case_editing"
    assert result.version == 3
    assert len(result.generated_cases) == 1
    assert result.generated_cases[0].test_type == "manual"
    assert result.generated_cases[0].automation_fit == "applicable"
    assert result.generated_cases[0].user_edited is False
    assert result.evidence_fingerprint == "fp-1"
    assert len(repo.updates) == 1


def test_generate_keeps_the_draft_source_provider() -> None:
    draft = _draft(source_provider="acme")
    chat = _FakeChat(content=_model_payload([_manual_case_payload()]))
    use_case = GenerateTestCases(chat_model=chat, repository=_MemoryRepo(draft))

    outcome = use_case.execute(
        GenerateTestCasesRequest(
            draft_id="draft-1",
            expected_version=2,
            evidence=(_evidence(),),
            evidence_fingerprint="fp-1",
        )
    )

    assert outcome.draft.source_provider == "acme"


def test_generate_mixed_manual_and_cucumber() -> None:
    draft = _draft(
        candidates=(
            _candidate(candidate_id="cand-1", test_type="manual"),
            _candidate(candidate_id="cand-2", title="Timeout", test_type="cucumber"),
        )
    )
    chat = _FakeChat(
        content=_model_payload(
            [_manual_case_payload("cand-1"), _cucumber_case_payload("cand-2")]
        )
    )
    repo = _MemoryRepo(draft)
    use_case = GenerateTestCases(chat_model=chat, repository=repo)

    result = use_case.execute(
        GenerateTestCasesRequest(
            draft_id="draft-1",
            expected_version=2,
            evidence=(_evidence(),),
            evidence_fingerprint="fp-1",
        )
    ).draft

    types = {case.candidate_id: case.test_type for case in result.generated_cases}
    assert types == {"cand-1": "manual", "cand-2": "cucumber"}


def test_generate_insufficient_evidence_gap_has_no_invented_steps() -> None:
    draft = _draft()
    chat = _FakeChat(
        content=_model_payload(
            [_manual_case_payload(availability="insufficient_evidence")]
        )
    )
    repo = _MemoryRepo(draft)
    use_case = GenerateTestCases(chat_model=chat, repository=repo)

    result = use_case.execute(
        GenerateTestCasesRequest(
            draft_id="draft-1",
            expected_version=2,
            evidence=(_evidence(),),
            evidence_fingerprint="fp-1",
        )
    ).draft

    case = result.generated_cases[0]
    assert case.availability == "insufficient_evidence"
    assert case.steps == ()
    assert case.gherkin == ""


def test_generate_rejects_coverage_review_without_model_or_write() -> None:
    draft = _draft(status="coverage_review")
    chat = _FakeChat(content=_model_payload([_manual_case_payload()]))
    repo = _MemoryRepo(draft)
    use_case = GenerateTestCases(chat_model=chat, repository=repo)

    with pytest.raises(TestDesignValidationError, match="ready|case_editing"):
        use_case.execute(
            GenerateTestCasesRequest(
                draft_id="draft-1",
                expected_version=2,
                evidence=(_evidence(),),
                evidence_fingerprint="fp-1",
            )
        )

    assert chat.calls == []
    assert repo.updates == []


def test_generate_skips_user_edited_unless_overwrite() -> None:
    edited = GeneratedTestCase(
        candidate_id="cand-1",
        test_type="manual",
        automation_fit="applicable",
        automation_rationale="Human edit.",
        availability="available",
        preconditions="Custom.",
        steps=("Custom step",),
        expected_result="Custom result.",
        gherkin="",
        user_edited=True,
    )
    draft = _draft(status="case_editing", generated_cases=(edited,))
    chat = _FakeChat(content=_model_payload([_manual_case_payload()]))
    repo = _MemoryRepo(draft)
    use_case = GenerateTestCases(chat_model=chat, repository=repo)

    outcome = use_case.execute(
        GenerateTestCasesRequest(
            draft_id="draft-1",
            expected_version=2,
            evidence=(_evidence(),),
            evidence_fingerprint="fp-1",
            overwrite_edited=False,
        )
    )

    assert outcome.draft.generated_cases[0].preconditions == "Custom."
    assert outcome.draft.generated_cases[0].user_edited is True
    assert outcome.skipped_edited_candidate_ids == ("cand-1",)
    assert chat.calls == []


def test_generate_skipping_every_edited_case_keeps_the_draft_source_provider() -> None:
    edited = GeneratedTestCase(
        candidate_id="cand-1",
        test_type="manual",
        automation_fit="applicable",
        automation_rationale="Human edit.",
        availability="available",
        preconditions="Custom.",
        steps=("Do",),
        expected_result="Done.",
        gherkin="",
        user_edited=True,
    )
    draft = _draft(
        status="case_editing", generated_cases=(edited,), source_provider="acme"
    )
    chat = _FakeChat()
    use_case = GenerateTestCases(chat_model=chat, repository=_MemoryRepo(draft))

    outcome = use_case.execute(
        GenerateTestCasesRequest(
            draft_id="draft-1",
            expected_version=2,
            evidence=(_evidence(),),
            evidence_fingerprint="fp-1",
            type_overrides=(TypeOverride(candidate_id="cand-1", test_type="manual"),),
        )
    )

    assert chat.calls == []
    assert outcome.draft.version == 3
    assert outcome.draft.source_provider == "acme"


def test_generate_overwrites_user_edited_when_requested() -> None:
    edited = GeneratedTestCase(
        candidate_id="cand-1",
        test_type="manual",
        automation_fit="applicable",
        automation_rationale="Human edit.",
        availability="available",
        preconditions="Custom.",
        steps=("Custom step",),
        expected_result="Custom result.",
        gherkin="",
        user_edited=True,
    )
    draft = _draft(status="case_editing", generated_cases=(edited,))
    chat = _FakeChat(content=_model_payload([_manual_case_payload()]))
    repo = _MemoryRepo(draft)
    use_case = GenerateTestCases(chat_model=chat, repository=repo)

    outcome = use_case.execute(
        GenerateTestCasesRequest(
            draft_id="draft-1",
            expected_version=2,
            evidence=(_evidence(),),
            evidence_fingerprint="fp-1",
            overwrite_edited=True,
        )
    )

    assert outcome.draft.generated_cases[0].preconditions == "User is logged out."
    assert outcome.draft.generated_cases[0].user_edited is False
    assert outcome.skipped_edited_candidate_ids == ()


def test_generate_missing_only_keeps_existing_cases_and_cucumber_shared() -> None:
    existing = GeneratedTestCase(
        candidate_id="cand-1",
        test_type="cucumber",
        automation_fit="applicable",
        automation_rationale="Human edit.",
        availability="available",
        preconditions="",
        steps=(),
        expected_result="",
        gherkin="Scenario: Valid\n  Given logged out",
        user_edited=True,
    )
    draft = _draft(
        status="case_editing",
        candidates=(
            _candidate(candidate_id="cand-1", test_type="cucumber"),
            _candidate(candidate_id="cand-2", title="Timeout", test_type="cucumber"),
        ),
        generated_cases=(existing,),
        cucumber_feature="Login",
        cucumber_background="",
    )
    chat = _FakeChat(
        content=_model_payload(
            [_cucumber_case_payload("cand-2")],
            cucumber_feature="Model feature",
            cucumber_background="Given model background",
        )
    )
    repo = _MemoryRepo(draft)
    use_case = GenerateTestCases(chat_model=chat, repository=repo)

    result = use_case.execute(
        GenerateTestCasesRequest(
            draft_id="draft-1",
            expected_version=2,
            evidence=(_evidence(),),
            evidence_fingerprint="fp-1",
            candidate_ids=("cand-2",),
        )
    ).draft

    by_id = {case.candidate_id: case for case in result.generated_cases}
    assert by_id["cand-1"] == existing
    assert by_id["cand-2"].gherkin == "Given slow network"
    assert result.cucumber_feature == "Login"
    assert result.cucumber_background == ""


def test_generate_rejects_invented_evidence_references() -> None:
    payload = _manual_case_payload()
    payload["evidence_references"] = [
        {"source_type": "github", "source_id": "invented"}
    ]
    draft = _draft()
    chat = _FakeChat(content=_model_payload([payload]))
    repo = _MemoryRepo(draft)
    use_case = GenerateTestCases(chat_model=chat, repository=repo)

    with pytest.raises(ToolFailureError):
        use_case.execute(
            GenerateTestCasesRequest(
                draft_id="draft-1",
                expected_version=2,
                evidence=(_evidence(),),
                evidence_fingerprint="fp-1",
            )
        )

    assert repo.updates == []


def test_generate_coerces_list_preconditions_and_string_steps() -> None:
    payload = _manual_case_payload()
    payload["preconditions"] = ["User is logged out.", "Cookies cleared"]
    payload["steps"] = "Enter credentials\nSubmit"
    payload["expected_result"] = "Home page loads.\nForm submits"
    draft = _draft()
    chat = _FakeChat(content=_model_payload([payload]))
    repo = _MemoryRepo(draft)
    use_case = GenerateTestCases(chat_model=chat, repository=repo)

    outcome = use_case.execute(
        GenerateTestCasesRequest(
            draft_id="draft-1",
            expected_version=2,
            evidence=(_evidence(),),
            evidence_fingerprint="fp-1",
        )
    )

    case = outcome.draft.generated_cases[0]
    assert case.preconditions == "User is logged out.\nCookies cleared"
    assert case.steps == ("Enter credentials", "Submit")
    assert case.expected_result == "Home page loads.\nForm submits"


def test_generate_strips_numbering_from_steps_and_expected() -> None:
    payload = _manual_case_payload()
    payload["preconditions"] = ["1) User is logged out."]
    payload["steps"] = ["1) Enter credentials", "2. Submit", "3) Confirm"]
    payload["expected_result"] = ["1) Home loads", "2) Form clears"]
    draft = _draft()
    chat = _FakeChat(content=_model_payload([payload]))
    repo = _MemoryRepo(draft)
    use_case = GenerateTestCases(chat_model=chat, repository=repo)

    outcome = use_case.execute(
        GenerateTestCasesRequest(
            draft_id="draft-1",
            expected_version=2,
            evidence=(_evidence(),),
            evidence_fingerprint="fp-1",
        )
    )

    case = outcome.draft.generated_cases[0]
    assert case.preconditions == "User is logged out."
    assert case.steps == ("Enter credentials", "Submit", "Confirm")
    assert case.expected_result == "Home loads\nForm clears"


def test_generate_shares_one_cucumber_feature_and_strips_per_case_feature() -> None:
    draft = _draft(
        candidates=(
            _candidate(candidate_id="cand-1", test_type="cucumber"),
            _candidate(candidate_id="cand-2", title="Second", test_type="cucumber"),
        )
    )
    chat = _FakeChat(
        content=_model_payload(
            [
                {
                    **_cucumber_case_payload("cand-1"),
                    "gherkin": (
                        "Feature: Personality\n"
                        "  Background:\n"
                        "    Given the app is running\n"
                        "  Scenario: First\n"
                        "    Then A"
                    ),
                },
                {
                    **_cucumber_case_payload("cand-2"),
                    "gherkin": (
                        "Feature: Other feature\n"
                        "  Background:\n"
                        "    Given ignored\n"
                        "  Scenario: Second\n"
                        "    Then B"
                    ),
                },
            ],
            cucumber_feature="Personality selection",
            cucumber_background="Given the chat is open",
        )
    )
    repo = _MemoryRepo(draft)
    use_case = GenerateTestCases(chat_model=chat, repository=repo)

    outcome = use_case.execute(
        GenerateTestCasesRequest(
            draft_id="draft-1",
            expected_version=2,
            evidence=(_evidence(),),
            evidence_fingerprint="fp-1",
        )
    )

    assert outcome.draft.cucumber_feature == "Personality selection"
    assert outcome.draft.cucumber_background == "Given the chat is open"
    assert outcome.draft.generated_cases[0].gherkin == "Then A"
    assert outcome.draft.generated_cases[1].gherkin == "Then B"


def test_generate_rejects_bad_automation_fit_without_write() -> None:
    payload = _manual_case_payload()
    payload["automation_fit"] = "maybe"
    draft = _draft()
    chat = _FakeChat(content=_model_payload([payload]))
    repo = _MemoryRepo(draft)
    use_case = GenerateTestCases(chat_model=chat, repository=repo)

    with pytest.raises(ToolFailureError):
        use_case.execute(
            GenerateTestCasesRequest(
                draft_id="draft-1",
                expected_version=2,
                evidence=(_evidence(),),
                evidence_fingerprint="fp-1",
            )
        )

    assert repo.updates == []


def test_type_overrides_applied_without_demoting() -> None:
    draft = _draft(candidates=(_candidate(test_type=None),))
    chat = _FakeChat(
        content=_model_payload(
            [
                {
                    **_cucumber_case_payload("cand-1"),
                    "test_type": "cucumber",
                }
            ]
        )
    )
    repo = _MemoryRepo(draft)
    use_case = GenerateTestCases(chat_model=chat, repository=repo)

    result = use_case.execute(
        GenerateTestCasesRequest(
            draft_id="draft-1",
            expected_version=2,
            evidence=(_evidence(),),
            evidence_fingerprint="fp-1",
            type_overrides=(TypeOverride(candidate_id="cand-1", test_type="cucumber"),),
        )
    ).draft

    assert result.status == "case_editing"
    assert result.candidates[0].test_type == "cucumber"
    assert result.generated_cases[0].test_type == "cucumber"
