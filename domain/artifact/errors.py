"""Artifact descriptor and index errors."""

from __future__ import annotations

from domain.errors import DomainValidationError


class ArtifactError(DomainValidationError):
    """Base for artifact descriptor failures."""


class ArtifactInputError(ArtifactError):
    """A descriptor, part, context assignment or key is invalid."""
