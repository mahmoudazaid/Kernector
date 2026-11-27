"""Deterministic matcher contracts (#375).

Matchers are pure ``MatchRequest -> MatchOutcome`` functions. They must not
touch the artifact index, document catalog, or relationship store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from domain.artifact.models import ArtifactDescriptor
from domain.knowledge import SourceReference
from domain.relationship.errors import RelationshipInputError
from domain.relationship.models import _require_extractor_id, _require_locator, _require_text


@dataclass(frozen=True, slots=True)
class MatchLimits:
    """Configured bounds for one matching run."""

    max_content_bytes: int
    max_mentions: int
    max_catalogue_entries: int
    max_compiled_pattern_size: int

    def __post_init__(self) -> None:
        for name in (
            "max_content_bytes",
            "max_mentions",
            "max_catalogue_entries",
            "max_compiled_pattern_size",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise RelationshipInputError(f"{name} must be a positive int")


@dataclass(frozen=True, slots=True)
class ProjectKeyCatalogue:
    """Known keys and prefixes for one project, already bounded by the use case."""

    keys: tuple[str, ...]
    prefixes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.keys, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.keys
        ):
            raise RelationshipInputError("keys must be a tuple of non-empty strings")
        if not isinstance(self.prefixes, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.prefixes
        ):
            raise RelationshipInputError(
                "prefixes must be a tuple of non-empty strings"
            )


@dataclass(frozen=True, slots=True)
class ApiOperationCatalogueEntry:
    """One current API operation identity in the project contract."""

    operation_id: str | None
    method_path: str | None

    def __post_init__(self) -> None:
        if self.operation_id is None and self.method_path is None:
            raise RelationshipInputError(
                "api operation entry needs operation_id or method_path"
            )
        if self.operation_id is not None:
            _require_text(self.operation_id, "operation_id")
        if self.method_path is not None:
            _require_text(self.method_path, "method_path")


@dataclass(frozen=True, slots=True)
class MatchRequest:
    """Pure matcher input assembled by ``MatchProjectReferences``."""

    content: str
    source: SourceReference
    revision: str
    subject: ArtifactDescriptor
    key_catalogue: ProjectKeyCatalogue
    api_operations: tuple[ApiOperationCatalogueEntry, ...]
    limits: MatchLimits

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise RelationshipInputError(
                f"content must be a string, got {type(self.content).__name__}"
            )
        if not isinstance(self.source, SourceReference):
            raise RelationshipInputError(
                f"source must be a SourceReference, got {type(self.source).__name__}"
            )
        _require_text(self.revision, "revision")
        if not isinstance(self.subject, ArtifactDescriptor):
            raise RelationshipInputError(
                "subject must be an ArtifactDescriptor, "
                f"got {type(self.subject).__name__}"
            )
        if not isinstance(self.key_catalogue, ProjectKeyCatalogue):
            raise RelationshipInputError(
                "key_catalogue must be a ProjectKeyCatalogue"
            )
        if not isinstance(self.api_operations, tuple) or not all(
            isinstance(item, ApiOperationCatalogueEntry)
            for item in self.api_operations
        ):
            raise RelationshipInputError(
                "api_operations must be a tuple of ApiOperationCatalogueEntry"
            )
        if not isinstance(self.limits, MatchLimits):
            raise RelationshipInputError("limits must be a MatchLimits")


@dataclass(frozen=True, slots=True)
class MatchMention:
    """One deterministic mention produced by a matcher."""

    identity: str
    locator: str
    rule_id: str
    relation_type: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.identity, "identity")
        _require_locator(self.locator)
        _require_extractor_id(self.rule_id, "rule_id")
        if self.relation_type is not None:
            from domain.relationship.models import _require_relation_type

            _require_relation_type(self.relation_type)


@dataclass(frozen=True, slots=True)
class MatchDiagnostic:
    """A non-edge observation from matching (bounds or unresolved operation)."""

    code: str
    rule_id: str
    source: SourceReference
    revision: str
    locator: str | None = None
    limit: int | None = None
    observed_count: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code.strip():
            raise RelationshipInputError("code must be a non-empty string")
        _require_extractor_id(self.rule_id, "rule_id")
        if not isinstance(self.source, SourceReference):
            raise RelationshipInputError(
                f"source must be a SourceReference, got {type(self.source).__name__}"
            )
        _require_text(self.revision, "revision")
        if self.locator is not None:
            _require_locator(self.locator)
        if self.limit is not None and (
            not isinstance(self.limit, int)
            or isinstance(self.limit, bool)
            or self.limit < 0
        ):
            raise RelationshipInputError("limit must be a non-negative int")
        if self.observed_count is not None and (
            not isinstance(self.observed_count, int)
            or isinstance(self.observed_count, bool)
            or self.observed_count < 0
        ):
            raise RelationshipInputError("observed_count must be a non-negative int")


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    """Pure matcher output: mentions plus diagnostics."""

    mentions: tuple[MatchMention, ...] = ()
    diagnostics: tuple[MatchDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.mentions, tuple) or not all(
            isinstance(item, MatchMention) for item in self.mentions
        ):
            raise RelationshipInputError("mentions must be a tuple of MatchMention")
        if not isinstance(self.diagnostics, tuple) or not all(
            isinstance(item, MatchDiagnostic) for item in self.diagnostics
        ):
            raise RelationshipInputError(
                "diagnostics must be a tuple of MatchDiagnostic"
            )


class DeterministicMatcher(Protocol):
    """Pure text matcher registered in composition (#375)."""

    @property
    def rule_id(self) -> str:
        """Canonical rule id stored on evidence as ``extractor_id``."""

    def match(self, request: MatchRequest) -> MatchOutcome:
        """Return mentions and diagnostics for ``request`` without I/O."""
