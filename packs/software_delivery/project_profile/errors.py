"""Pack-local validation errors for project profiling (#387)."""

from domain.errors import DomainValidationError


class ProjectProfileValidationError(DomainValidationError):
    """Invalid project profile evidence, fact, or contract input."""
