"""Tests for test-design draft codec serialization."""

from __future__ import annotations

import json

import pytest

from domain.knowledge import SourceReference
from packs.software_delivery.test_design.codec import (
    DRAFT_SCHEMA_VERSION,
    decode_draft_payload,
    encode_draft_payload,
)
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.models import (
    TestCandidate,
    TestCoverageDraft,
)


def _ref() -> SourceReference:
    return SourceReference("PROJ-42", "jira")


def _draft(**overrides: object) -> TestCoverageDraft:
    base: dict[str, object] = {
        "draft_id": "draft-1",
        "workspace_id": "ws-1",
        "conversation_id": "conv-1",
        "source_reference": _ref(),
        "ticket_identifier": "KERN-293",
        "status": "coverage_review",
        "candidates": (
            TestCandidate(
                candidate_id="cand-1",
                title="Valid login",
                category="positive",
                rationale="AC covers login.",
                evidence_references=(_ref(),),
                selected=True,
                origin="suggested",
            ),
        ),
        "version": 1,
    }
    base.update(overrides)
    return TestCoverageDraft(**base)  # type: ignore[arg-type]


def test_encode_decode_round_trip_preserves_draft() -> None:
    draft = _draft(status="ready", version=3)
    payload = encode_draft_payload(draft)
    restored = decode_draft_payload(payload, draft_id=draft.draft_id, version=draft.version)

    assert restored == draft
    parsed = json.loads(payload)
    assert parsed["schema_version"] == DRAFT_SCHEMA_VERSION
    assert "scenarios" not in parsed


def test_decode_maps_legacy_scenario_editing_status_and_ignores_scenarios() -> None:
    payload = json.dumps(
        {
            "schema_version": 1,
            "workspace_id": "ws-1",
            "conversation_id": "conv-1",
            "source_reference": {"source_type": "jira", "source_id": "PROJ-42"},
            "ticket_identifier": "KERN-293",
            "status": "scenario_editing",
            "candidates": [],
            "scenarios": [{"scenario_id": "scen-1"}],
        }
    )
    restored = decode_draft_payload(payload, draft_id="draft-1", version=1)
    assert restored.status == "ready"
    assert restored.generated_cases == ()
    assert restored.evidence_fingerprint is None


def test_decode_rejects_unknown_schema_version() -> None:
    payload = json.dumps(
        {
            "schema_version": 99,
            "workspace_id": "ws-1",
            "conversation_id": "conv-1",
            "source_reference": {"source_type": "jira", "source_id": "PROJ-42"},
            "ticket_identifier": "KERN-293",
            "status": "coverage_review",
            "candidates": [],
        }
    )
    with pytest.raises(TestDesignValidationError, match="schema_version"):
        decode_draft_payload(payload, draft_id="draft-1", version=1)


def test_decode_rejects_invalid_json() -> None:
    with pytest.raises(TestDesignValidationError, match="payload"):
        decode_draft_payload("{not-json", draft_id="draft-1", version=1)


def test_decode_rejects_invalid_draft_shape() -> None:
    payload = json.dumps(
        {
            "schema_version": DRAFT_SCHEMA_VERSION,
            "workspace_id": "ws-1",
            "conversation_id": "conv-1",
            "source_reference": {"source_type": "jira", "source_id": "PROJ-42"},
            "ticket_identifier": "293",
            "status": "coverage_review",
            "candidates": [],
        }
    )
    with pytest.raises(TestDesignValidationError, match="ticket_identifier"):
        decode_draft_payload(payload, draft_id="draft-1", version=1)


def test_decode_maps_legacy_categories() -> None:
    payload = json.dumps(
        {
            "schema_version": 1,
            "workspace_id": "ws-1",
            "conversation_id": "conv-1",
            "source_reference": {"source_type": "jira", "source_id": "PROJ-42"},
            "ticket_identifier": "KERN-293",
            "status": "coverage_review",
            "candidates": [
                {
                    "candidate_id": "cand-1",
                    "title": "Legacy happy path",
                    "category": "happy_path",
                    "rationale": "old allowlist",
                    "evidence_references": [
                        {"source_type": "jira", "source_id": "PROJ-42"}
                    ],
                    "selected": False,
                    "origin": "suggested",
                },
                {
                    "candidate_id": "cand-2",
                    "title": "Legacy ACL",
                    "category": "permission_security",
                    "rationale": "old allowlist",
                    "evidence_references": [
                        {"source_type": "jira", "source_id": "PROJ-42"}
                    ],
                    "selected": False,
                    "origin": "suggested",
                },
            ],
            "scenarios": [],
            "coverage_gaps": [
                {
                    "category": "integration",
                    "detail": "legacy gap",
                }
            ],
        }
    )
    restored = decode_draft_payload(payload, draft_id="draft-1", version=1)

    assert restored.candidates[0].category == "positive"
    assert restored.candidates[1].category == "negative"
    assert restored.candidates[0].test_type is None


def test_v4_round_trip_preserves_generated_cases_and_fingerprint() -> None:
    from packs.software_delivery.test_design.models import GeneratedTestCase

    case = GeneratedTestCase(
        candidate_id="cand-1",
        test_type="manual",
        automation_fit="applicable",
        automation_rationale="Stable.",
        availability="available",
        preconditions="Logged out.",
        steps=("Login",),
        expected_result="Home.",
        gherkin="",
        user_edited=True,
    )
    draft = _draft(
        status="case_editing",
        candidates=(
            TestCandidate(
                candidate_id="cand-1",
                title="Valid login",
                category="positive",
                rationale="AC covers login.",
                evidence_references=(_ref(),),
                selected=True,
                origin="suggested",
                test_type="manual",
            ),
        ),
        generated_cases=(case,),
        evidence_fingerprint="fp-abc",
        version=4,
    )
    payload = encode_draft_payload(draft)
    restored = decode_draft_payload(
        payload, draft_id=draft.draft_id, version=draft.version
    )
    assert restored == draft
    assert json.loads(payload)["schema_version"] == 4


def test_decode_v2_keeps_steps_and_expected_result() -> None:
    payload = json.dumps(
        {
            "schema_version": 2,
            "workspace_id": "ws-1",
            "conversation_id": "conv-1",
            "source_reference": {
                "source_type": "jira",
                "source_id": "PROJ-42",
            },
            "ticket_identifier": "KERN-293",
            "status": "case_editing",
            "candidates": [
                {
                    "candidate_id": "cand-1",
                    "title": "Valid login",
                    "category": "positive",
                    "rationale": "AC covers login.",
                    "evidence_references": [
                        {"source_type": "jira", "source_id": "PROJ-42"}
                    ],
                    "selected": True,
                    "origin": "suggested",
                    "test_type": "manual",
                }
            ],
            "generated_cases": [
                {
                    "candidate_id": "cand-1",
                    "test_type": "manual",
                    "automation_fit": "applicable",
                    "automation_rationale": "Stable.",
                    "availability": "available",
                    "preconditions": "Logged out.",
                    "steps": ["Login", "Open home"],
                    "expected_result": "Home.\nDashboard.",
                    "gherkin": "",
                    "user_edited": False,
                }
            ],
            "evidence_fingerprint": "fp-abc",
            "cucumber_feature": "",
            "cucumber_background": "",
        }
    )
    restored = decode_draft_payload(payload, draft_id="draft-1", version=4)
    assert restored.generated_cases[0].steps == ("Login", "Open home")
    assert restored.generated_cases[0].expected_result == "Home.\nDashboard."




def test_decode_v3_migrates_manual_step_objects() -> None:
    payload = json.dumps(
        {
            "schema_version": 3,
            "workspace_id": "ws-1",
            "conversation_id": "conv-1",
            "source_reference": {
                "source_type": "jira",
                "source_id": "PROJ-42",
            },
            "ticket_identifier": "KERN-293",
            "status": "case_editing",
            "candidates": [
                {
                    "candidate_id": "cand-1",
                    "title": "Valid login",
                    "category": "positive",
                    "rationale": "AC covers login.",
                    "evidence_references": [
                        {"source_type": "jira", "source_id": "PROJ-42"}
                    ],
                    "selected": True,
                    "origin": "suggested",
                    "test_type": "manual",
                }
            ],
            "generated_cases": [
                {
                    "candidate_id": "cand-1",
                    "test_type": "manual",
                    "automation_fit": "applicable",
                    "automation_rationale": "Stable.",
                    "availability": "available",
                    "preconditions": "Logged out.",
                    "steps": [
                        {"action": "Login", "expected": "Home."},
                        {"action": "Open home", "expected": "Dashboard."},
                    ],
                    "gherkin": "",
                    "user_edited": False,
                }
            ],
            "evidence_fingerprint": "fp-abc",
            "cucumber_feature": "",
            "cucumber_background": "",
        }
    )
    restored = decode_draft_payload(payload, draft_id="draft-1", version=4)
    assert restored.generated_cases[0].steps == ("Login", "Open home")
    assert restored.generated_cases[0].expected_result == "Home.\nDashboard."

def test_decode_v1_defaults_new_fields() -> None:
    payload = json.dumps(
        {
            "schema_version": 1,
            "workspace_id": "ws-1",
            "conversation_id": "conv-1",
            "source_reference": {"source_type": "jira", "source_id": "PROJ-42"},
            "ticket_identifier": "KERN-293",
            "status": "ready",
            "candidates": [
                {
                    "candidate_id": "cand-1",
                    "title": "Valid login",
                    "category": "positive",
                    "rationale": "AC covers login.",
                    "evidence_references": [
                        {"source_type": "jira", "source_id": "PROJ-42"}
                    ],
                    "selected": True,
                    "origin": "suggested",
                }
            ],
        }
    )
    restored = decode_draft_payload(payload, draft_id="draft-1", version=2)
    assert restored.generated_cases == ()
    assert restored.evidence_fingerprint is None
    assert restored.candidates[0].test_type is None
    assert DRAFT_SCHEMA_VERSION == 4
