"""Pack-local validation errors for the test-design workflow."""

from domain.errors import DomainValidationError


class TestDesignValidationError(DomainValidationError):
    """Invalid test-design draft, candidate, or scenario input."""

    __test__ = False
