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
    CoverageGap,
    TestCandidate,
    TestCoverageDraft,
    TestScenario,
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
        "scenarios": (),
        "coverage_gaps": (
            CoverageGap(
                category="negative",
                detail="No ACL criteria.",
            ),
        ),
        "version": 1,
    }
    base.update(overrides)
    return TestCoverageDraft(**base)  # type: ignore[arg-type]


def test_encode_decode_round_trip_preserves_draft() -> None:
    draft = _draft(
        status="scenario_editing",
        scenarios=(
            TestScenario(
                scenario_id="scen-1",
                candidate_id="cand-1",
                title="Valid login",
                category="positive",
                preconditions=("User exists",),
                steps=("Open login", "Submit"),
                expected_result="Dashboard shown",
                evidence_references=(_ref(),),
            ),
        ),
        version=3,
    )
    payload = encode_draft_payload(draft)
    restored = decode_draft_payload(payload, draft_id=draft.draft_id, version=draft.version)

    assert restored == draft
    parsed = json.loads(payload)
    assert parsed["schema_version"] == DRAFT_SCHEMA_VERSION


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
            "scenarios": [],
            "coverage_gaps": [],
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
            "scenarios": [],
            "coverage_gaps": [],
        }
    )
    with pytest.raises(TestDesignValidationError, match="ticket_identifier"):
        decode_draft_payload(payload, draft_id="draft-1", version=1)
