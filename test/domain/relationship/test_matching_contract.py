"""Deterministic matcher request/outcome contracts (#375)."""

from __future__ import annotations

import pytest

from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor, ContextAssignment
from domain.knowledge import SourceReference
from domain.relationship.errors import RelationshipInputError
from domain.relationship.matching import (
    ApiOperationCatalogueEntry,
    MatchDiagnostic,
    MatchLimits,
    MatchMention,
    MatchOutcome,
    MatchRequest,
    ProjectKeyCatalogue,
)
from domain.relationship.models import EvidenceRef


def _ref(source_id: str = "gh/acme/proj-tests:tests/orders/cancel_order.robot") -> SourceReference:
    return SourceReference(source_id, "github")


def _descriptor() -> ArtifactDescriptor:
    return ArtifactDescriptor(
        reference=_ref(),
        revision="a1b2c3",
        kind=ArtifactKind.AUTOMATED_TEST,
        contexts=(ContextAssignment("testing", "role_default"),),
        external_keys=(),
    )


def test_evidence_ref_accepts_segmented_rule_id_as_extractor_id() -> None:
    evidence = EvidenceRef(
        source=_ref(),
        revision="a1b2c3",
        locator="line=6",
        extractor_id="key_mention.tag",
    )

    assert evidence.extractor_id == "key_mention.tag"


def test_evidence_ref_rejects_invalid_segmented_extractor_id() -> None:
    with pytest.raises(RelationshipInputError, match="extractor_id"):
        EvidenceRef(
            source=_ref(),
            revision="a1b2c3",
            locator="line=6",
            extractor_id="KeyMention.Tag",
        )
    with pytest.raises(RelationshipInputError, match="extractor_id"):
        EvidenceRef(
            source=_ref(),
            revision="a1b2c3",
            locator="line=6",
            extractor_id=".key_mention",
        )


def test_match_request_outcome_and_mention_round_trip() -> None:
    request = MatchRequest(
        content='[Tags]    PROJ-123',
        source=_ref(),
        revision="a1b2c3",
        subject=_descriptor(),
        key_catalogue=ProjectKeyCatalogue(
            keys=("PROJ-123", "PROJ-140"),
            prefixes=("PROJ",),
        ),
        api_operations=(
            ApiOperationCatalogueEntry(
                operation_id="cancelOrder",
                method_path="POST /orders/{}/cancel",
            ),
        ),
        limits=MatchLimits(
            max_content_bytes=1_048_576,
            max_mentions=100,
            max_catalogue_entries=10_000,
            max_compiled_pattern_size=65_536,
        ),
    )
    mention = MatchMention(
        identity="PROJ-123",
        locator="line=1",
        rule_id="key_mention.tag",
        relation_type="automates",
    )
    diagnostic = MatchDiagnostic(
        code="mention_overflow",
        rule_id="key_mention.tag",
        source=_ref(),
        revision="a1b2c3",
        locator="line=1",
        limit=100,
        observed_count=101,
    )
    outcome = MatchOutcome(mentions=(mention,), diagnostics=(diagnostic,))

    assert request.subject.kind == ArtifactKind.AUTOMATED_TEST
    assert outcome.mentions[0].identity == "PROJ-123"
    assert outcome.diagnostics[0].code == "mention_overflow"
    assert outcome.diagnostics[0].limit == 100


def test_match_mention_requires_segmented_rule_id() -> None:
    with pytest.raises(RelationshipInputError, match="rule_id"):
        MatchMention(
            identity="PROJ-123",
            locator="line=1",
            rule_id="BAD",
            relation_type="automates",
        )


def test_match_diagnostic_requires_code_and_rule_id() -> None:
    with pytest.raises(RelationshipInputError, match="code"):
        MatchDiagnostic(
            code="",
            rule_id="key_mention.tag",
            source=_ref(),
            revision="a1b2c3",
        )
