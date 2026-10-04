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
        "source_provider": "jira",
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


def test_round_trip_keeps_provider_distinct_from_source_type() -> None:
    draft = _draft(source_provider="acme")

    payload = encode_draft_payload(draft)
    restored = decode_draft_payload(payload, draft_id=draft.draft_id, version=1)

    assert restored.source_provider == "acme"
    assert restored.source_reference.source_type == "jira"
    assert json.loads(payload)["source_provider"] == "acme"


@pytest.mark.parametrize("schema_version", [1, 2, 3, 4])
def test_legacy_payload_without_provider_derives_it_from_source_type(
    schema_version: int,
) -> None:
    payload = json.dumps(
        {
            "schema_version": schema_version,
            "workspace_id": "ws-1",
            "conversation_id": "conv-1",
            "source_reference": {"source_type": "github", "source_id": "issue:I_1"},
            "ticket_identifier": "acme/app#7",
            "status": "coverage_review",
            "candidates": [],
        }
    )

    restored = decode_draft_payload(payload, draft_id="draft-1", version=1)

    assert restored.source_provider == "github"


def test_current_schema_payload_requires_provider() -> None:
    payload = json.dumps(
        {
            "schema_version": DRAFT_SCHEMA_VERSION,
            "workspace_id": "ws-1",
            "conversation_id": "conv-1",
            "source_reference": {"source_type": "github", "source_id": "issue:I_1"},
            "ticket_identifier": "acme/app#7",
            "status": "coverage_review",
            "candidates": [],
        }
    )

    with pytest.raises(TestDesignValidationError, match="source_provider"):
        decode_draft_payload(payload, draft_id="draft-1", version=1)


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
            "source_provider": "jira",
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


def test_round_trip_preserves_generated_cases_and_fingerprint() -> None:
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
    assert json.loads(payload)["schema_version"] == DRAFT_SCHEMA_VERSION


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

    as_v4 = json.loads(payload) | {"schema_version": 4}
    with pytest.raises(TestDesignValidationError, match="list of strings"):
        decode_draft_payload(json.dumps(as_v4), draft_id="draft-1", version=4)


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
    assert restored.evidence_origin == "live"
    assert DRAFT_SCHEMA_VERSION == 6


def test_client_supplied_draft_round_trips_its_evidence() -> None:
    draft = _draft(
        source_reference=SourceReference("client:KERN-293", "client_supplied"),
        source_provider="client",
        evidence_origin="client_supplied",
        client_evidence_text="# Login\n\nTicket: KERN-293",
    )

    payload = encode_draft_payload(draft)
    restored = decode_draft_payload(payload, draft_id=draft.draft_id, version=1)

    assert restored == draft
    assert restored.evidence_origin == "client_supplied"
    assert restored.client_evidence_text == "# Login\n\nTicket: KERN-293"
    parsed = json.loads(payload)
    assert parsed["schema_version"] == 6
    assert parsed["evidence_origin"] == "client_supplied"


def test_schema_5_payload_decodes_as_live() -> None:
    payload = json.dumps(
        {
            "schema_version": 5,
            "workspace_id": "ws-1",
            "conversation_id": "conv-1",
            "source_reference": {"source_type": "github", "source_id": "issue:I_1"},
            "ticket_identifier": "acme/app#7",
            "source_provider": "github",
            "status": "coverage_review",
            "candidates": [],
        }
    )

    restored = decode_draft_payload(payload, draft_id="draft-1", version=1)

    assert restored.evidence_origin == "live"
    assert restored.client_evidence_text == ""


def test_client_supplied_draft_requires_evidence_text() -> None:
    with pytest.raises(TestDesignValidationError, match="client_evidence_text"):
        _draft(evidence_origin="client_supplied", client_evidence_text="  ")


def test_live_draft_rejects_client_evidence_text() -> None:
    with pytest.raises(TestDesignValidationError, match="client_evidence_text"):
        _draft(evidence_origin="live", client_evidence_text="supplied")


def test_draft_rejects_unknown_evidence_origin() -> None:
    with pytest.raises(TestDesignValidationError, match="evidence_origin"):
        _draft(evidence_origin="scraped")
