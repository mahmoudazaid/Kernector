"""Relationship domain errors (#374)."""

from __future__ import annotations

from domain.errors import DomainValidationError


class RelationshipError(DomainValidationError):
    """Base for relationship contract failures."""


class RelationshipInputError(RelationshipError):
    """A relationship, evidence ref or unresolved key is invalid."""


class ArtifactNotVisibleError(RelationshipError):
    """The artifact key is not visible in the requested project."""
