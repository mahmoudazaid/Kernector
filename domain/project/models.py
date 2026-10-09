"""Project identity, source association and component contracts (ADR 0011).

Context roles are opaque tokens: their vocabulary is registered by packs, so
this module checks only their shape.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from enum import StrEnum

from domain.knowledge import SourceReference
from domain.project.errors import ProjectInputError
from domain.project.paths import normalize_path_prefix

_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+")
_MAX_IDENTIFIER_LENGTH = 64
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_TOKEN = re.compile(r"[a-z][a-z0-9_]*")
_MAX_TOKEN_LENGTH = 64
_MAX_TEXT_LENGTH = 512

COMPONENT_REASON_ASSOCIATION_DEFAULT = "association_default"
COMPONENT_REASON_OPERATOR = "operator"
COMPONENT_REASONS = frozenset(
    {COMPONENT_REASON_ASSOCIATION_DEFAULT, COMPONENT_REASON_OPERATOR}
)


def require_identifier(value: object, field_name: str) -> str:
    """Return ``value`` when it has the ADR 0006 identifier shape."""
    if not isinstance(value, str):
        raise ProjectInputError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    if len(value) > _MAX_IDENTIFIER_LENGTH or not _IDENTIFIER.fullmatch(value):
        raise ProjectInputError(
            f"{field_name} must fullmatch [A-Za-z0-9_-]+ and be at most "
            f"{_MAX_IDENTIFIER_LENGTH} characters"
        )
    return value


def require_token(value: object, field_name: str) -> str:
    """Return ``value`` when it is a lowercase opaque token."""
    if not isinstance(value, str):
        raise ProjectInputError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    if len(value) > _MAX_TOKEN_LENGTH or not _TOKEN.fullmatch(value):
        raise ProjectInputError(
            f"{field_name} must fullmatch [a-z][a-z0-9_]* and be at most "
            f"{_MAX_TOKEN_LENGTH} characters"
        )
    return value


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ProjectInputError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    if not value.strip():
        raise ProjectInputError(f"{field_name} must be non-empty")
    if len(value) > _MAX_TEXT_LENGTH:
        raise ProjectInputError(
            f"{field_name} must be at most {_MAX_TEXT_LENGTH} characters"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ProjectInputError(f"{field_name} must not contain control characters")
    return value


def _require_version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProjectInputError("version must be a positive integer")
    return value


def new_project_id() -> str:
    """Return a fresh opaque ``project_id``; never derived from a name."""
    return f"prj_{uuid.uuid4().hex}"


def new_component_id() -> str:
    """Return a fresh opaque ``component_id``."""
    return f"cmp_{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class Project:
    """A project in one workspace, referenced only by ``project_id``."""

    project_id: str
    name: str
    slug: str
    version: int

    def __post_init__(self) -> None:
        require_identifier(self.project_id, "project_id")
        _require_text(self.name, "name")
        if (
            not isinstance(self.slug, str)
            or len(self.slug) > _MAX_IDENTIFIER_LENGTH
            or not _SLUG.fullmatch(self.slug)
        ):
            raise ProjectInputError(
                "slug must be lowercase letters and digits separated by single "
                f"hyphens, at most {_MAX_IDENTIFIER_LENGTH} characters"
            )
        _require_version(self.version)


@dataclass(frozen=True, slots=True)
class SourceScope:
    """Opaque, provider-neutral part of a connected source."""

    connector_id: str
    scope_kind: str
    scope_value: str

    def __post_init__(self) -> None:
        _require_text(self.connector_id, "connector_id")
        require_token(self.scope_kind, "scope_kind")
        _require_text(self.scope_value, "scope_value")


class AssociationState(StrEnum):
    """Operator decision on an association; only ``confirmed`` scopes reads."""

    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


_TRANSITIONS = frozenset(
    {
        (AssociationState.SUGGESTED, AssociationState.CONFIRMED),
        (AssociationState.SUGGESTED, AssociationState.REJECTED),
        (AssociationState.REJECTED, AssociationState.CONFIRMED),
    }
)


def can_transition(current: AssociationState, target: AssociationState) -> bool:
    """Return whether an operator may move an association between states."""
    return (current, target) in _TRANSITIONS


def require_roles(roles: object) -> tuple[str, ...]:
    """Return ``roles`` when it is a tuple of unique context tokens."""
    if not isinstance(roles, tuple):
        raise ProjectInputError(
            f"roles must be a tuple, got {type(roles).__name__}"
        )
    for role in roles:
        require_token(role, "role")
    if len(set(roles)) != len(roles):
        raise ProjectInputError("roles must not repeat")
    return roles


@dataclass(frozen=True, slots=True)
class SourceAssociation:
    """Links a project to a source scope with context roles."""

    project_id: str
    scope: SourceScope
    roles: tuple[str, ...]
    state: AssociationState
    evidence: tuple[SourceReference, ...]
    created_by: str
    version: int

    def __post_init__(self) -> None:
        require_identifier(self.project_id, "project_id")
        if not isinstance(self.scope, SourceScope):
            raise ProjectInputError(
                f"scope must be a SourceScope, got {type(self.scope).__name__}"
            )
        require_roles(self.roles)
        if not isinstance(self.state, AssociationState):
            raise ProjectInputError(
                f"state must be an AssociationState, got {type(self.state).__name__}"
            )
        if not isinstance(self.evidence, tuple) or not all(
            isinstance(item, SourceReference) for item in self.evidence
        ):
            raise ProjectInputError("evidence must be a tuple of SourceReference")
        _require_text(self.created_by, "created_by")
        _require_version(self.version)


@dataclass(frozen=True, slots=True)
class ComponentMember:
    """A confirmed association scope, optionally narrowed by a path prefix."""

    scope: SourceScope
    path_prefix: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.scope, SourceScope):
            raise ProjectInputError(
                f"scope must be a SourceScope, got {type(self.scope).__name__}"
            )
        if normalize_path_prefix(self.path_prefix) != self.path_prefix:
            raise ProjectInputError("path_prefix must be canonical")


@dataclass(frozen=True, slots=True)
class ProjectComponent:
    """A separately deployed or owned unit; it has no type field."""

    component_id: str
    project_id: str
    name: str
    members: tuple[ComponentMember, ...]
    reason: str
    version: int

    def __post_init__(self) -> None:
        require_identifier(self.component_id, "component_id")
        require_identifier(self.project_id, "project_id")
        _require_text(self.name, "name")
        if not isinstance(self.members, tuple) or not all(
            isinstance(member, ComponentMember) for member in self.members
        ):
            raise ProjectInputError("members must be a tuple of ComponentMember")
        if not self.members:
            raise ProjectInputError("a component needs at least one member")
        if len(set(self.members)) != len(self.members):
            raise ProjectInputError("component members must not repeat")
        if self.reason not in COMPONENT_REASONS:
            raise ProjectInputError("reason must be association_default or operator")
        _require_version(self.version)


class ContextAssociationStatus(StrEnum):
    """Structural coverage: does a confirmed association declare the context?

    ``not_associated`` matches the ADR 0011 decision 10.5 outcome literal.
    ``associated`` is not an evidence outcome and does not mean ``available``.
    """

    ASSOCIATED = "associated"
    NOT_ASSOCIATED = "not_associated"


@dataclass(frozen=True, slots=True)
class ContextAssociationCoverage:
    """One registered context and the confirmed scopes that declare it."""

    context: str
    status: ContextAssociationStatus
    scopes: tuple[SourceScope, ...]

    def __post_init__(self) -> None:
        require_token(self.context, "context")
        if not isinstance(self.status, ContextAssociationStatus):
            raise ProjectInputError("status must be a ContextAssociationStatus")
        associated = self.status is ContextAssociationStatus.ASSOCIATED
        if associated != bool(self.scopes):
            raise ProjectInputError(
                "associated coverage needs scopes; not_associated has none"
            )


class ComponentResolutionStatus(StrEnum):
    """How a document resolved to a component within one project."""

    RESOLVED = "resolved"
    UNASSIGNED = "unassigned"
    INVALID_PATH = "invalid_path"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ComponentResolution:
    """Per-project component resolution for one document."""

    project_id: str
    status: ComponentResolutionStatus
    component_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        require_identifier(self.project_id, "project_id")
        count = len(self.component_ids)
        expected = {
            ComponentResolutionStatus.RESOLVED: count == 1,
            ComponentResolutionStatus.AMBIGUOUS: count >= 2,
            ComponentResolutionStatus.UNASSIGNED: count == 0,
            ComponentResolutionStatus.INVALID_PATH: count == 0,
        }
        if not expected.get(self.status, False):
            raise ProjectInputError("component_ids do not fit the resolution status")


@dataclass(frozen=True, slots=True)
class AssociationEvidence:
    """Authoritative provider-declared link from one scope to another.

    ``reference`` and ``locator`` cite where the source declares the link, for
    example a Jira remote link on an issue in ``source_scope``.
    """

    source_scope: SourceScope
    target_scope: SourceScope
    reference: SourceReference
    locator: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_scope, SourceScope) or not isinstance(
            self.target_scope, SourceScope
        ):
            raise ProjectInputError("evidence scopes must be SourceScope values")
        if not isinstance(self.reference, SourceReference):
            raise ProjectInputError("evidence reference must be a SourceReference")
        _require_text(self.locator, "locator")
