"""Composition errors for the test-design workflow facade."""


class TestDesignUnavailableError(RuntimeError):
    """Software Delivery pack is disabled; test-design cannot run."""

    __test__ = False


class TestDesignNotFoundError(RuntimeError):
    """Draft id is unknown or outside the caller's workspace."""

    __test__ = False


class TestDesignVersionConflictError(RuntimeError):
    """Compare-and-swap expected_version did not match the stored draft."""

    __test__ = False


class TestDesignValidationError(ValueError):
    """Caller-supplied test-design request failed validation."""

    __test__ = False


class UnsupportedSourceLocatorError(TestDesignValidationError):
    """No registered Test Design source accepts the issue locator."""

    __test__ = False


class TestDesignEvidenceChangedError(RuntimeError):
    """Live Issue evidence no longer matches the confirmed draft fingerprint."""

    __test__ = False
