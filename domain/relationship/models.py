"""Evidence-backed relationship contracts (ADR 0011, #374).

Origin, verification and freshness are independent axes. Relation types are
opaque tokens (shape only); meaning and Jira link mapping live outside domain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from math import isfinite

from domain.artifact.models import ArtifactRef
from domain.knowledge import SourceReference
from domain.relationship.errors import RelationshipInputError

_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+")
_TOKEN = re.compile(r"[a-z][a-z0-9_]*")
_RELATION_TYPE = re.compile(r"[a-z][a-z0-9_]*(?::[\w-]+)?", re.UNICODE)
_MAX_IDENTIFIER_LENGTH = 64
_MAX_TOKEN_LENGTH = 64
_MAX_TEXT_LENGTH = 512
_MAX_KEY_LENGTH = 256
_MAX_LOCATOR_LENGTH = 512

ORIGIN_PROVIDER_DECLARED = "provider_declared"
ORIGIN_DETERMINISTIC = "deterministic"
ORIGIN_INFERRED = "inferred"
ORIGIN_HUMAN_CONFIRMED = "human_confirmed"
_ORIGINS = frozenset(
    {
        ORIGIN_PROVIDER_DECLARED,
        ORIGIN_DETERMINISTIC,
        ORIGIN_INFERRED,
        ORIGIN_HUMAN_CONFIRMED,
    }
)

VERIFICATION_UNVERIFIED = "unverified"
VERIFICATION_VERIFIED = "verified"
VERIFICATION_REJECTED = "rejected"
_VERIFICATIONS = frozenset(
    {
        VERIFICATION_UNVERIFIED,
        VERIFICATION_VERIFIED,
        VERIFICATION_REJECTED,
    }
)

FRESHNESS_CURRENT = "current"
FRESHNESS_STALE = "stale"
FRESHNESS_REMOVED = "removed"
_FRESHNESS = frozenset(
    {FRESHNESS_CURRENT, FRESHNESS_STALE, FRESHNESS_REMOVED}
)

_START_VERIFIED = frozenset(
    {
        ORIGIN_PROVIDER_DECLARED,
        ORIGIN_DETERMINISTIC,
        ORIGIN_HUMAN_CONFIRMED,
    }
)


def _require_token(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise RelationshipInputError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    if len(value) > _MAX_TOKEN_LENGTH or not _TOKEN.fullmatch(value):
        raise RelationshipInputError(
            f"{field_name} must fullmatch [a-z][a-z0-9_]* and be at most "
            f"{_MAX_TOKEN_LENGTH} characters"
        )
    return value


def _require_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise RelationshipInputError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    if len(value) > _MAX_IDENTIFIER_LENGTH or not _IDENTIFIER.fullmatch(value):
        raise RelationshipInputError(
            f"{field_name} must fullmatch [A-Za-z0-9_-]+ and be at most "
            f"{_MAX_IDENTIFIER_LENGTH} characters"
        )
    return value


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise RelationshipInputError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    if not value.strip():
        raise RelationshipInputError(f"{field_name} must be non-empty")
    if len(value) > _MAX_TEXT_LENGTH:
        raise RelationshipInputError(
            f"{field_name} must be at most {_MAX_TEXT_LENGTH} characters"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RelationshipInputError(
            f"{field_name} must not contain control characters"
        )
    return value


def _require_key(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise RelationshipInputError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    if not value.strip():
        raise RelationshipInputError(f"{field_name} must be non-empty")
    if len(value) > _MAX_KEY_LENGTH:
        raise RelationshipInputError(
            f"{field_name} must be at most {_MAX_KEY_LENGTH} characters"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RelationshipInputError(
            f"{field_name} must not contain control characters"
        )
    return value


def _require_relation_type(value: object) -> str:
    if not isinstance(value, str):
        raise RelationshipInputError(
            f"relation_type must be a string, got {type(value).__name__}"
        )
    if len(value) > _MAX_KEY_LENGTH or not _RELATION_TYPE.fullmatch(value):
        raise RelationshipInputError(
            "relation_type must be a lowercase token or provider-prefixed "
            f"token and at most {_MAX_KEY_LENGTH} characters"
        )
    return value


def _require_locator(value: object) -> str:
    if not isinstance(value, str):
        raise RelationshipInputError(
            f"locator must be a string, got {type(value).__name__}"
        )
    if not value.strip():
        raise RelationshipInputError("locator must be non-empty")
    if len(value) > _MAX_LOCATOR_LENGTH:
        raise RelationshipInputError(
            f"locator must be at most {_MAX_LOCATOR_LENGTH} characters"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RelationshipInputError("locator must not contain control characters")
    return value


def _require_endpoint(value: object, field_name: str) -> ArtifactRef | UnresolvedKey:
    if isinstance(value, ArtifactRef) or isinstance(value, UnresolvedKey):
        return value
    raise RelationshipInputError(
        f"{field_name} must be ArtifactRef or UnresolvedKey, "
        f"got {type(value).__name__}"
    )


def _format_decision_at(at: datetime) -> str:
    if at.tzinfo is None:
        raise RelationshipInputError("decision time must be timezone-aware")
    return at.isoformat()


@dataclass(frozen=True, slots=True)
class UnresolvedKey:
    """An external key not yet bound to an artifact in the index."""

    key: str

    def __post_init__(self) -> None:
        _require_key(self.key, "key")


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """One observation that supports a relationship edge."""

    source: SourceReference
    revision: str
    locator: str
    extractor_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceReference):
            raise RelationshipInputError(
                f"source must be a SourceReference, got {type(self.source).__name__}"
            )
        _require_text(self.revision, "revision")
        _require_locator(self.locator)
        _require_token(self.extractor_id, "extractor_id")


@dataclass(frozen=True, slots=True)
class Relationship:
    """Directed, evidence-backed edge scoped to one project."""

    relationship_id: str
    project_id: str
    subject: ArtifactRef | UnresolvedKey
    relation_type: str
    object: ArtifactRef | UnresolvedKey
    origin: str
    verification: str
    confidence: float
    freshness: str
    evidence: tuple[EvidenceRef, ...]
    first_seen_at: str
    last_verified_at: str | None = None
    decision_actor: str | None = None
    decision_at: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.relationship_id, "relationship_id")
        _require_identifier(self.project_id, "project_id")
        _require_endpoint(self.subject, "subject")
        _require_relation_type(self.relation_type)
        _require_endpoint(self.object, "object")
        origin = _require_token(self.origin, "origin")
        if origin not in _ORIGINS:
            raise RelationshipInputError(f"origin is not a known tier: {origin}")
        verification = _require_token(self.verification, "verification")
        if verification not in _VERIFICATIONS:
            raise RelationshipInputError(
                f"verification is not a known state: {verification}"
            )
        freshness = _require_token(self.freshness, "freshness")
        if freshness not in _FRESHNESS:
            raise RelationshipInputError(
                f"freshness is not a known state: {freshness}"
            )
        if not isinstance(self.confidence, (int, float)) or isinstance(
            self.confidence, bool
        ):
            raise RelationshipInputError("confidence must be a number")
        if not isfinite(float(self.confidence)) or not (
            0.0 <= float(self.confidence) <= 1.0
        ):
            raise RelationshipInputError("confidence must be between 0 and 1")
        if not isinstance(self.evidence, tuple) or not all(
            isinstance(item, EvidenceRef) for item in self.evidence
        ):
            raise RelationshipInputError("evidence must be a tuple of EvidenceRef")
        if not self.evidence:
            raise RelationshipInputError("evidence must not be empty")
        _require_text(self.first_seen_at, "first_seen_at")
        if self.last_verified_at is not None:
            _require_text(self.last_verified_at, "last_verified_at")
        if self.decision_actor is not None:
            _require_text(self.decision_actor, "decision_actor")
        if self.decision_at is not None:
            _require_text(self.decision_at, "decision_at")
        if origin in _START_VERIFIED and verification == VERIFICATION_UNVERIFIED:
            raise RelationshipInputError(
                f"{origin} relationships must start verified, not unverified"
            )
        if origin == ORIGIN_INFERRED and verification != VERIFICATION_UNVERIFIED:
            if self.decision_actor is None or self.decision_at is None:
                raise RelationshipInputError(
                    "inferred relationships must start unverified; "
                    "verified or rejected inferred edges require an explicit "
                    "human decision that records actor and time"
                )

    def confirm(self, *, actor: str, at: datetime) -> Relationship:
        """Record a human confirmation; preserve origin."""
        actor_text = _require_text(actor, "actor")
        decided_at = _format_decision_at(at)
        if self.verification not in {
            VERIFICATION_UNVERIFIED,
            VERIFICATION_REJECTED,
        }:
            raise RelationshipInputError(
                "confirm requires unverified or rejected verification"
            )
        return replace(
            self,
            verification=VERIFICATION_VERIFIED,
            decision_actor=actor_text,
            decision_at=decided_at,
            last_verified_at=decided_at,
        )

    def reject(self, *, actor: str, at: datetime) -> Relationship:
        """Record a human rejection; preserve origin."""
        actor_text = _require_text(actor, "actor")
        decided_at = _format_decision_at(at)
        if self.verification not in {
            VERIFICATION_UNVERIFIED,
            VERIFICATION_VERIFIED,
        }:
            raise RelationshipInputError(
                "reject requires unverified or verified verification"
            )
        return replace(
            self,
            verification=VERIFICATION_REJECTED,
            decision_actor=actor_text,
            decision_at=decided_at,
        )


@dataclass(frozen=True, slots=True)
class ProviderLink:
    """One canonical provider-declared link observation ready to record."""

    relation_type: str
    subject_key: str
    object_key: str
    locator: str
    subject_part_key: str | None = None
    object_part_key: str | None = None

    def __post_init__(self) -> None:
        _require_relation_type(self.relation_type)
        _require_key(self.subject_key, "subject_key")
        _require_key(self.object_key, "object_key")
        _require_locator(self.locator)
        if self.subject_part_key is not None:
            _require_key(self.subject_part_key, "subject_part_key")
        if self.object_part_key is not None:
            _require_key(self.object_part_key, "object_part_key")
